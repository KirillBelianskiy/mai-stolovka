"use client";

import { useEffect, useState, type FormEvent } from "react";
import { ArrowRight, LogOut, RefreshCw, UserRound } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import type { UserProfile } from "@/lib/auth";

export function ProfilePanel() {
  const auth = useAuth();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [name, setName] = useState("");
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");

  useEffect(() => {
    if (auth.status !== "authenticated") {
      setProfile(null);
      setName("");
      return;
    }
    let current = true;
    setProfile(auth.credentials?.user ?? null);
    setName(auth.credentials?.user.full_name ?? "");
    setLoadingProfile(true);
    void auth
      .refreshProfile()
      .then((value) => {
        if (!current) return;
        setProfile(value);
        setName(value.full_name);
        setFailure("");
      })
      .catch(() => {
        if (current) setFailure("Не удалось обновить профиль. Повторите попытку.");
      })
      .finally(() => {
        if (current) setLoadingProfile(false);
      });
    return () => {
      current = false;
    };
  }, [auth.status, auth.credentials?.user.id, auth.refreshProfile]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setFailure("");
    setMessage("");
    try {
      const updated = await auth.saveFullName(name);
      setProfile(updated);
      setName(updated.full_name);
      setMessage("Имя сохранено.");
    } catch {
      setFailure("Не удалось сохранить имя. Проверьте подключение и повторите попытку.");
    } finally {
      setSaving(false);
    }
  }

  async function signOut() {
    setFailure("");
    setMessage("");
    try {
      await auth.signOut();
      setProfile(null);
      setName("");
      setMessage("Вы вышли из профиля.");
    } catch {
      setFailure("Сессию не удалось завершить. Попробуйте ещё раз.");
    }
  }

  async function switchAccount() {
    setFailure("");
    setMessage("");
    const succeeded = await auth.switchAccount();
    if (succeeded) setMessage("Аккаунт Telegram подтверждён.");
    else setFailure(auth.error ?? "Не удалось подтвердить аккаунт Telegram.");
  }

  return (
    <section id="profile" className="profile-section" aria-labelledby="profile-heading">
      <div className="profile-heading">
        <div>
          <p className="eyebrow">Ваш аккаунт</p>
          <h2 id="profile-heading">Профиль</h2>
        </div>
        <UserRound size={24} aria-hidden="true" />
      </div>

      {auth.status === "loading" ? (
        <p className="profile-note" role="status">Проверяем вход в аккаунт…</p>
      ) : auth.status === "authenticated" ? (
        <>
          {profile && (
            <form className="profile-form" onSubmit={submit}>
              <label htmlFor="profile-full-name">Имя</label>
              <input
                id="profile-full-name"
                name="full_name"
                autoComplete="name"
                required
                minLength={1}
                maxLength={256}
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={saving || loadingProfile || auth.busy}
              />
              {profile.username && (
                <p className="profile-note">Telegram: @{profile.username}</p>
              )}
              <div className="profile-actions">
                <button className="primary-button" type="submit" disabled={saving || loadingProfile || auth.busy}>
                  {saving ? "Сохраняем…" : "Сохранить имя"}
                  <ArrowRight size={17} aria-hidden="true" />
                </button>
                {auth.canUseTelegram && (
                  <button className="text-button" type="button" onClick={() => void switchAccount()} disabled={auth.busy}>
                    Сменить аккаунт Telegram
                  </button>
                )}
                <button className="profile-logout" type="button" onClick={() => void signOut()} disabled={auth.busy}>
                  <LogOut size={16} aria-hidden="true" /> Выйти
                </button>
              </div>
            </form>
          )}
          {!profile && (
            <div className="profile-state" role="status">
              <p>{loadingProfile ? "Загружаем профиль…" : "Профиль не загрузился."}</p>
              <button className="text-button" type="button" onClick={() => void auth.refreshProfile()} disabled={auth.busy}>
                <RefreshCw size={15} aria-hidden="true" /> Повторить
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="profile-state">
          <p>{auth.error ?? "Войдите через Telegram, чтобы открыть профиль."}</p>
          {auth.canUseTelegram ? (
            <button className="primary-button" type="button" onClick={() => void auth.signIn()} disabled={auth.busy}>
              {auth.busy ? "Проверяем…" : "Войти через Telegram"}
              <ArrowRight size={17} aria-hidden="true" />
            </button>
          ) : (
            <p className="profile-note">Откройте приложение внутри Telegram.</p>
          )}
          <button className="text-button" type="button" onClick={() => void auth.retry()} disabled={auth.busy}>
            <RefreshCw size={15} aria-hidden="true" /> Проверить сессию снова
          </button>
        </div>
      )}
      {(failure || auth.error || message) && (
        <p className={failure || auth.error ? "profile-feedback error" : "profile-feedback"} role="status">
          {failure || auth.error || message}
        </p>
      )}
    </section>
  );
}
