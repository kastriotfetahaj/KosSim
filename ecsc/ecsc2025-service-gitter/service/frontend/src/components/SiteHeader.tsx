import { getUserFromSessionToken } from "@/lib/auth";
import Link from "next/link";

function HeaderButton({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center h-full px-4 py-4 hover:bg-sleek-details-subtle active:bg-sleek-details">
      {children}
    </div>
  );
}

export async function SiteHeader({
  children,
  actions = [],
}: {
  children: React.ReactNode;
  actions?: React.ReactNode[];
}) {
  const user = await getUserFromSessionToken();

  const userActions = user ? (
    <>
      <HeaderButton>Hello, {user.username}</HeaderButton>
      <form action="/logout" method="POST" className="flex h-full">
        <button type="submit" className="flex">
          <HeaderButton>Logout</HeaderButton>
        </button>
      </form>
    </>

  ) : (
    <>
      <Link href="/login" className="flex h-full">
        <HeaderButton>Login</HeaderButton>
      </Link>
      <Link href="/register" className="flex h-full">
        <HeaderButton>Sign up</HeaderButton>
      </Link>
    </>
  );

  return (
    <div className="flex justify-between gap-2 border-b border-sleek-details w-full bg-sleek-fill">
      <span className="flex items-center">{children}</span>
      <div className="flex ml-auto h-full">
        {actions.map((action, index) => (
          <div
            key={`custom-${index}`}
            className="flex hover:bg-sleek-details-subtle active:bg-sleek-details"
          >
            {action}
          </div>
        ))}
        <div className="flex [&>*]:border-l [&>*]:border-sleek-details">
          {userActions}
        </div>
      </div>
    </div>
  );
}
