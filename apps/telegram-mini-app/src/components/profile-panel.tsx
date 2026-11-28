"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ChevronRight } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { ScreenHeader, Sheet } from "@/components/customer-ui";
import type { UserProfile } from "@/lib/auth";

export function ProfilePanel({ onBack, onHistory }: { onBack: () => void; onHistory: () => void }) {
  const auth = useAuth();
  const { refreshProfile } = auth;
  const [profile, setProfile] = useState<UserProfile | null>(auth.credentials?.user ?? null);
  const [name, setName] = useState("");
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [profileError, setProfileError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setProfileError("");
    try {
      setProfile(await refreshProfile());
    } catch {
      setProfileError("Не удалось обновить профиль.");
    } finally {
      setLoading(false);
    }
  }, [refreshProfile]);
  useEffect(() => { void refresh(); }, [refresh]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || !name.trim()) return;
    setSaving(true);
    setFailure("");
    setMessage("");
    try {
      setProfile(await auth.saveFullName(name));
      setEditing(false);
      setMessage("Имя сохранено.");
    } catch {
      setFailure("Не удалось сохранить имя. Попробуйте ещё раз.");
    } finally {
      setSaving(false);
    }
  }

  async function signOut() {
    setFailure("");
    setMessage("");
    try {
      await auth.signOut();
    } catch {
      setFailure("Сессию не удалось завершить. Попробуйте ещё раз.");
    }
  }

  return (
    <section className="scene profile-scene" aria-labelledby="profile-heading">
      <div className="photo-banner plane-art profile-banner">
        <ScreenHeader onBack={onBack} />
        {profile && (
          <>
            <span className="profile-avatar" aria-hidden="true">{Array.from(profile.full_name.trim())[0]?.toLocaleUpperCase("ru")}</span>
            <p className="profile-name">{profile.full_name}</p>
            {profile.username && <p>@{profile.username}</p>}
          </>
        )}
      </div>
      <div className="screen-content profile-content">
        <h1 id="profile-heading">Профиль</h1>
        {loading && <p className="sr-only" role="status">Загружаем профиль…</p>}
        {profile && (
          <button className="profile-row" disabled={loading || auth.busy} onClick={() => {
            setName(profile.full_name);
            setFailure("");
            setMessage("");
            setEditing(true);
          }}>
            <span>Имя</span><small>{profile.full_name}</small><ChevronRight size={16} aria-hidden="true" />
          </button>
        )}
        {auth.credentials?.user.role === "CLIENT" && (
          <button className="profile-row" onClick={onHistory}>
            <span>История заказов</span><ChevronRight size={16} aria-hidden="true" />
          </button>
        )}
        <button className="profile-row" disabled={auth.busy || saving} onClick={() => void signOut()}>
          <span>Выйти</span><ChevronRight size={16} aria-hidden="true" />
        </button>
        {auth.canUseTelegram && (
          <button className="text-button profile-switch" disabled={auth.busy || saving}
            onClick={async () => {
              setMessage("");
              setFailure("");
              if (await auth.switchAccount()) {
                setMessage("Аккаунт Telegram подтверждён.");
                await refresh();
              }
            }}>Сменить аккаунт Telegram</button>
        )}
        {profileError && (
          <p role="alert">{profileError} <button className="text-button" onClick={() => void refresh()}>Повторить</button></p>
        )}
        {!editing && (failure || auth.error) && <p role="alert" className="error-text">{failure || auth.error}</p>}
        {message && <p role="status">{message}</p>}
      </div>
      {editing && (
        <Sheet title="Изменить имя" onDismiss={() => { if (!saving) setEditing(false); }}>
          <form onSubmit={submit} className="profile-form">
            <label htmlFor="profile-name">Имя</label>
            <input id="profile-name" autoComplete="name" required maxLength={256} autoFocus
              value={name} onChange={(event) => setName(event.target.value)} disabled={saving || auth.busy} />
            {failure && <p role="alert" className="error-text">{failure}</p>}
            <button className="primary-button" disabled={saving || auth.busy || !name.trim()}>
              {saving ? "Сохраняем…" : "Сохранить имя"}
            </button>
          </form>
        </Sheet>
      )}
    </section>
  );
}
