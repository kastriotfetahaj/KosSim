export function ListItem({ children }: { children: React.ReactNode }) {
  return <div className="border-y border-sleek-details bg-sleek-details-subtle p-2">{children}</div>;
}

export function List({
  children,
  emptyMessage = "No items",
}: {
  children: React.ReactNode;
  emptyMessage?: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      {children}
      {!children ||
        (Array.isArray(children) && children.length === 0 && (
          <div className="text-center text-gray-500 p-2">{emptyMessage}</div>
        ))}
    </div>
  );
}
