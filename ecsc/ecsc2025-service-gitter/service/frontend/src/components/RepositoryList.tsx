import Link from "next/link";
import { List, ListItem } from "@/components/List";
import { Repository } from "@/lib/repos";

type RepositoryListProps = {
  repositories: Repository[];
  detailed?: boolean;
};

export function RepositoryList({ repositories, detailed = true }: RepositoryListProps) {
  return (
    <List>
      {repositories.map((repository) => (
        <Link href={`/${repository.owner_username}/${repository.name}`} key={`repository-${repository.id}`}>
          <ListItem key={repository.id}>
            {detailed ? (
              <div className="flex items-center gap-4">
                {repository.logo ? (
                  <img
                    src={repository.logo}
                    alt={`${repository.name} logo`}
                    className="w-12 h-12 rounded-lg object-cover border-2 border-sleek-details flex-shrink-0"
                  />
                ) : (
                  <div className="w-12 h-12 rounded-lg bg-gray-700 border-2 border-sleek-details flex items-center justify-center flex-shrink-0">
                    <span className="text-gray-400 text-xs font-mono">
                      {repository.name.charAt(0).toUpperCase()}
                    </span>
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <h2 className="text-lg font-semibold text-gray-200 truncate">{repository.owner_username} / {repository.name}</h2>
                  <span className="text-sm text-gray-500 line-clamp-2">
                    {repository.public_description || "No description provided"}
                  </span>
                </div>
              </div>
            ) : (
              repository.name
            )}
          </ListItem>
        </Link>
      ))}
    </List>
  );
} 