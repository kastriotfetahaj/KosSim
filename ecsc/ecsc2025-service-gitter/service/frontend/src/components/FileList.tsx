import { GitFileOrFolder } from "@/lib/repos";
import Link from "next/link";
import { FiFolder, FiFile } from "react-icons/fi";
import { formatDistanceToNow } from 'date-fns';

interface FileListProps {
  objects: GitFileOrFolder[];
  organization: string;
  repository: string;
  currentPath: string[];
}

export function FileList({
  objects,
  organization,
  repository,
  currentPath,
}: FileListProps) {
  const basePath = `/${organization}/${repository}/tree`;
  const currentPathString = currentPath.map(s => encodeURIComponent(s)).join("/");

  return (
    <div className="flex flex-col items-center border-sleek-details w-full [&>*:not(:last-child)]:border-b">
      {objects.map((obj) => (
        <Link
          key={obj.name}
          href={`${basePath}/${currentPathString}${currentPathString ? "/" : ""
            }${encodeURIComponent(obj.name)}`}
          className="flex items-center w-full p-3 cursor-pointer hover:bg-sleek-details-subtle transition-colors"
        >
          <div className="pr-2">
            {obj.type === "folder" ? <FiFolder /> : <FiFile />}
          </div>
          <div className="ml">{obj.name}</div>
          <div className="text-slate-500 ml-auto">
            {obj.modified ? formatDistanceToNow(new Date(obj.modified), { addSuffix: true }) : ""}
          </div>
        </Link>
      ))}
    </div>
  );
}
