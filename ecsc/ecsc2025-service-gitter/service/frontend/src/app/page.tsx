import { getUserFromSessionToken } from "@/lib/auth";
import Link from "next/link";
import { getRepositories } from "@/lib/repos";
import { Header } from "@/components/Header";
import { RepositoryList } from "@/components/RepositoryList";
export default async function Home() {
  const user = await getUserFromSessionToken();
  const repositories = user ? await getRepositories(user.id) : [];

  return (
    <>
      <div className="flex flex-col w-full">
        {user && (
          <div className="flex flex-col w-full gap-2">
            <Header
              actions={[
                <Link href={`/${user?.username}/new`} key={`create-repository-${user?.username}`}>
                  <span className="flex text-2xl font-bold h-full items-center px-4">
                    +
                  </span>
                </Link>,
              ]}
            >
              Your repositories
            </Header>
            <RepositoryList repositories={repositories} detailed={true} />
          </div>
        )}
      </div>
    </>
  );
}
