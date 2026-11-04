"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  AccountChangedError,
  AuthApiError,
  loginTelegram,
  loadProfile,
  logout as logoutRequest,
  readTelegramInitData,
  restoreOrLogin,
  switchTelegramAccount,
  updateProfile,
  withTokenRefresh,
  type AuthCredentials,
  type UserProfile,
} from "@/lib/auth";

type AuthStatus = "loading" | "anonymous" | "authenticated" | "error";

type AuthContextValue = {
  status: AuthStatus;
  credentials: AuthCredentials | null;
  error: string | null;
  busy: boolean;
  canUseTelegram: boolean;
  retry: () => Promise<void>;
  signIn: () => Promise<boolean>;
  switchAccount: () => Promise<boolean>;
  refreshProfile: () => Promise<UserProfile>;
  saveFullName: (name: string) => Promise<UserProfile>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function describeError(error: unknown): string {
  if (error instanceof AuthApiError && error.status === 503) {
    return "Сервис авторизации временно недоступен. Попробуйте ещё раз.";
  }
  if (error instanceof AuthApiError && error.status === 401) {
    return "Сессия закончилась. Откройте приложение в Telegram и войдите снова.";
  }
  return "Не удалось связаться с сервисом авторизации. Проверьте подключение и повторите попытку.";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [initData, setInitData] = useState<string | undefined>(undefined);
  const [initDataReady, setInitDataReady] = useState(false);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [credentials, setCredentials] = useState<AuthCredentials | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const bootstrapRef = useRef<Promise<void> | null>(null);
  const signedOutRef = useRef(false);
  const credentialsRef = useRef<AuthCredentials | null>(null);
  const statusRef = useRef<AuthStatus>("loading");
  const generationRef = useRef(0);

  useEffect(() => {
    // The SDK reader caches the full launch URL (including initData) in sessionStorage.
    // Remove only that legacy cache and use the current/navigation URL directly.
    try {
      sessionStorage.removeItem("tapps/launchParams");
    } catch {
      // Storage may be disabled.
    }
    let value = readTelegramInitData(window.location.href);
    if (!value) {
      try {
        value = readTelegramInitData(
          window.location.href,
          performance.getEntriesByType("navigation")[0]?.name,
        );
      } catch {
        // Navigation timing may be unavailable.
      }
    }
    setInitData(value);
    setInitDataReady(true);
  }, []);

  const accept = useCallback((value: AuthCredentials, clearError = true) => {
    generationRef.current += 1;
    credentialsRef.current = value;
    statusRef.current = "authenticated";
    setCredentials(value);
    setStatus("authenticated");
    if (clearError) setError(null);
  }, []);

  const reject = useCallback((reason: unknown) => {
    generationRef.current += 1;
    credentialsRef.current = null;
    const nextStatus = reason instanceof AuthApiError && reason.status === 401 ? "anonymous" : "error";
    statusRef.current = nextStatus;
    setCredentials(null);
    setStatus(nextStatus);
    setError(describeError(reason));
  }, []);

  const runBootstrap = useCallback(async () => {
    setBusy(true);
    setStatus("loading");
    setError(null);
    try {
      accept(await restoreOrLogin(initData, fetch));
    } catch (reason) {
      reject(reason);
    } finally {
      setBusy(false);
    }
  }, [accept, initData, reject]);

  useEffect(() => {
    if (!initDataReady || signedOutRef.current || bootstrapRef.current) return;
    bootstrapRef.current = runBootstrap();
  }, [initDataReady, runBootstrap]);

  const retry = useCallback(async () => {
    signedOutRef.current = false;
    bootstrapRef.current = runBootstrap();
    await bootstrapRef.current;
    bootstrapRef.current = null;
  }, [runBootstrap]);

  const signIn = useCallback(async (): Promise<boolean> => {
    if (!initData) {
      setError("Для входа откройте это приложение в Telegram.");
      return false;
    }
    setBusy(true);
    setError(null);
    generationRef.current += 1;
    try {
      accept(await loginTelegram(initData));
      signedOutRef.current = false;
      return true;
    } catch (reason) {
      reject(reason);
      return false;
    } finally {
      setBusy(false);
    }
  }, [accept, initData, reject]);

  const switchAccount = useCallback(async (): Promise<boolean> => {
    if (!initData) {
      setError("Для смены аккаунта откройте приложение в Telegram.");
      return false;
    }
    setBusy(true);
    setError(null);
    generationRef.current += 1;
    const current = credentialsRef.current;
    if (!current) {
      setBusy(false);
      setError("Сначала войдите в аккаунт.");
      return false;
    }
    const result = await switchTelegramAccount(current, initData);
    if (result.ok) accept(result.credentials);
    else setError(describeError(result.error));
    setBusy(false);
    return result.ok;
  }, [accept, initData]);

  const withFreshToken = useCallback(
    async <T,>(operation: (token: string) => Promise<T>): Promise<T> => {
      const generation = generationRef.current;
      const current = credentialsRef.current;
      if (statusRef.current !== "authenticated" || !current) {
        throw new AuthApiError("Authentication is required", 401);
      }
      const result = await withTokenRefresh(
        current.access_token,
        async (token) => {
          if (generation !== generationRef.current) {
            throw new AuthApiError("Authentication changed", 401);
          }
          return operation(token);
        },
        async () => {
          if (generation !== generationRef.current) {
            throw new AuthApiError("Authentication changed", 401);
          }
          return restoreOrLogin(initData);
        },
        current.user.id,
      ).catch((refreshError) => {
        if (
          generation === generationRef.current &&
          refreshError instanceof AccountChangedError
        ) {
          accept(refreshError.credentials);
          setError(
            "Аккаунт изменился. Предыдущее действие отменено — проверьте профиль и повторите его.",
          );
        }
        if (
          generation === generationRef.current &&
          refreshError instanceof AuthApiError &&
          refreshError.status === 401
        ) {
          reject(refreshError);
        }
        throw refreshError;
      });
      if (generation !== generationRef.current) {
        throw new AuthApiError("Authentication changed", 409);
      }
      if (result.credentials) accept(result.credentials);
      return result.value;
    },
    [accept, initData, reject],
  );

  const refreshProfile = useCallback(async () => {
    const generation = generationRef.current;
    const profile = await withFreshToken((token) => loadProfile(token));
    const current = credentialsRef.current;
    if (current && generation === generationRef.current) {
      accept({ ...current, user: profile }, false);
    }
    return profile;
  }, [accept, withFreshToken]);

  const saveFullName = useCallback(async (name: string) => {
    const profile = await withFreshToken((token) => updateProfile(token, name));
    const current = credentialsRef.current;
    if (current?.user.id === profile.id) {
      accept({ ...current, user: profile });
    }
    return profile;
  }, [accept, withFreshToken]);

  const signOut = useCallback(async () => {
    setBusy(true);
    setError(null);
    generationRef.current += 1;
    try {
      await logoutRequest();
      signedOutRef.current = true;
      credentialsRef.current = null;
      statusRef.current = "anonymous";
      setCredentials(null);
      setStatus("anonymous");
    } catch (reason) {
      setError("Не удалось завершить сессию. Проверьте подключение и повторите попытку.");
      throw reason;
    } finally {
      setBusy(false);
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        status,
        credentials,
        error,
        busy,
        canUseTelegram: Boolean(initData),
        retry,
        signIn,
        switchAccount,
        refreshProfile,
        saveFullName,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
