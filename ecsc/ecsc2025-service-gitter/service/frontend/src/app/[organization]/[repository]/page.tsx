import { getUserFromSessionToken } from "@/lib/auth";
import { getRepository as getRepository, getRepositoryMembers, hasAccess } from "@/lib/repos";
import Link from "next/link";
import { headers } from "next/headers";
import LogoSettings from "@/components/LogoSettings";
import RepositoryMembers from "@/components/RepositoryMembers";
import ErrorScreen from "@/components/ErrorScreen";
import { SettingsCard } from "@/components/SettingsCard";

export default async function RepositoryPage({
  params,
}: {
  params: Promise<{ organization: string; repository: string }>;
}) {
  const user = await getUserFromSessionToken();

  if (!user) {
    return <ErrorScreen title="Unauthorized" message="You must be logged in to access this repository" />;
  }

  const { organization, repository } = await params;

  const repo = await getRepository(
    decodeURIComponent(organization),
    decodeURIComponent(repository)
  );

  if (!repo) {
    return <ErrorScreen title="Not Found" message="Repository not found" />;
  }

  const isOwner = repo.owner_id === user.id;
  
  if (!isOwner) {
    repo.private_description = "Private description only readable by owner";
  }

  if (!await hasAccess(repo.id, user.id)) {
    return (
      <ErrorScreen
        title="Access Denied"
        message={`You are not allowed to access ${repo.name} repository (id: ${repo.id})`}
      />
    );
  }

  const members = await getRepositoryMembers(repo.id);

  const host = (await headers()).get("host")?.split(":")?.[0];


  return (
    <div className="flex flex-col w-full">
      <main className="p-6">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-4">
            {repo.logo && (
              <img
                src={repo.logo}
                alt={`${repo.name} logo`}
                className="w-16 h-16 rounded-lg object-cover border-2 border-sleek-details"
              />
            )}
            <div>
              <h1 className="text-2xl font-bold text-gray-200">{repo.name}</h1>
              <p className="text-md text-gray-400">owned by {organization}</p>
            </div>
          </div>
          <div className="mt-4 md:mt-0">
            <Link
              href={`/${organization}/${repository}/tree/`}
              className="inline-block rounded-md bg-sleek-button px-4 py-2 hover:underline"
            >
              Browse Files
            </Link>
          </div>
        </div>

        <div className="mt-6 space-y-6">
          <div>
            <h2 className="text-lg font-semibold mb-2 border-b border-gray-700 pb-2">
              Clone URL
            </h2>
            <p className="text-gray-300 pt-2">
              <code>{`git clone ssh://git@${host}:9201/${organization}/${repository}`}</code>
            </p>
          </div>
        
        </div>

        <div className="mt-6 space-y-6">
          <div>
            <h2 className="text-lg font-semibold mb-2 border-b border-gray-700 pb-2">
              Public Description
            </h2>
            <p className="text-gray-300 pt-2">
              {repo.public_description || "No public description provided."}
            </p>
          </div>
          <div>
            <h2 className="text-lg font-semibold mb-2 border-b border-gray-700 pb-2">
              Private Description
            </h2>
            <p className="text-gray-300 pt-2">
              {repo.private_description || "No private description provided."}
            </p>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
          <SettingsCard title="Access">
            <RepositoryMembers repo={repo} members={members} />
          </SettingsCard>
          <SettingsCard title="Settings">
              <LogoSettings
                repository={repo}
                organization={organization}
              />
          </SettingsCard>
        </div>
      </main>
    </div>
  );
}
