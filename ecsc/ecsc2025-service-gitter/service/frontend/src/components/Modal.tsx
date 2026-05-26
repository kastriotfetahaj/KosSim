export function Modal({
  children,
  title,
}: {
  children: React.ReactNode;
  title: string;
}) {
  return (
    <div className="w-full max-w-md bg-sleek-background p-8 shadow-md">
      <h1 className="mb-6 text-2xl font-bold text-center">{title}</h1>
      {children}
    </div>
  );
}
