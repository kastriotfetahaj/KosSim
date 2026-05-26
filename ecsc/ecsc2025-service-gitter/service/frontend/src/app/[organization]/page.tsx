import { redirect } from "next/navigation";
import { getUserFromSessionToken } from "@/lib/auth";
import { getRepositoriesForOrganizationForUser, organizationExists } from "@/lib/repos";
import Link from "next/link";
import { Header } from "@/components/Header";
import { RepositoryList } from "@/components/RepositoryList";
import ErrorScreen from "@/components/ErrorScreen";
type Props = {
  params: Promise<{
    organization: string;
  }>;
};

export default async function RepositoryPage({ params }: Props) {
  const { organization } = await params;

  const user = await getUserFromSessionToken();

  if (!user) {
    redirect("/login");
  }

  if (!await organizationExists(organization)) {
    return <ErrorScreen title="Not Found" message="Organization not found" />;
  }

  const repositories = await getRepositoriesForOrganizationForUser(organization);

  return (
    <div className="flex flex-col w-full gap-2">
      <Header
        actions={[
          <Link href={`/${organization}/new`} key={`create-repository-${organization}`}>
            <span className="flex text-2xl font-bold h-full items-center px-4">
              +
            </span>
          </Link>,
        ]}
      >
        {organization} repositories
      </Header>
      {repositories && <RepositoryList repositories={repositories} detailed={true} />}
    </div>
  );
}
