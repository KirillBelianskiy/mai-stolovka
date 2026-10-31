export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col justify-center gap-6 px-6 py-16">
      <p className="text-sm font-semibold tracking-widest text-primary">МАИ ЕДА / ЭТАП 1</p>
      <h1 className="max-w-2xl text-4xl font-semibold tracking-tight sm:text-6xl">Рабочее место столовой</h1>
      <p className="max-w-xl text-lg leading-relaxed text-muted-foreground">Заказы, приготовление и выдача — скоро здесь.</p>
      <div className="mt-4 rounded-2xl border border-border bg-card p-6">
        <h2 className="font-semibold">Основа приложения готова</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Это стартовый экран для разработки. Авторизация и работа с заказами появятся на следующих этапах.
        </p>
      </div>
    </main>
  );
}
