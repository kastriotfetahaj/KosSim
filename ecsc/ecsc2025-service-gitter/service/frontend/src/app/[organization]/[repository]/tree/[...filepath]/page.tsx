"use server";

import ReactMarkdown from "react-markdown";
import { prepareWorkingTree, getFileContent, getFolders, isFolder, exists, getRepository, hasAccess } from "@/lib/repos";
import { FileList } from "@/components/FileList";
import Link from "next/link";
import { getUserFromSessionToken } from "@/lib/auth";
import { codeToHtml } from 'shiki'
import ErrorScreen from "@/components/ErrorScreen";

type Props = {
  params: Promise<{
    organization: string;
    repository: string;
    filepath: string[];
  }>;
};


const ending_to_language = {
  "md": "markdown",
  "ts": "typescript",
  "js": "javascript",
  "jsx": "javascript",
  "tsx": "typescript",
  "py": "python",
  "rb": "ruby",
  "php": "php",
  "html": "html",
  "css": "css",
  "json": "json",
}

const supported_languages = Object.keys(ending_to_language);


function getFileType(file_extension: string) {
  if (file_extension === "md") {
    return "markdown";
  } else if(supported_languages.includes(file_extension)) {
    return "code";
  }
  return "text";
}


async function FilePreview({
  file_content,
  filepath,
}: {
  file_content: string;
  filepath: string[];
}) {


  const file_extension = filepath.at(-1)?.split(".").at(-1) || "";

  const file_type = getFileType(file_extension);

  if(file_type === "markdown") {

  return (
    <>
      <h1 className="text-xl font-semibold border-b-2 px-4 py-2 border-sleek-details sticky top-0 bg-sleek-background">
        {filepath.join("/")}
      </h1>
      <div className="flex flex-1 bg-sleek-background">
        <div className="prose prose-slate prose-invert p-4">
          <ReactMarkdown>{file_content}</ReactMarkdown>
        </div>
      </div>
    </>
  );
  } else {

    const html = await codeToHtml(file_content, {
      lang: ending_to_language[file_extension as keyof typeof ending_to_language] ?? "text",
      theme: 'synthwave-84',
    })

    
    return (
      <div className="flex flex-col flex-1">
        <h1 className="text-xl font-semibold border-b-2 px-4 py-2 border-slate-200 sticky top-0 bg-sleek-background">
          {filepath.join("/")}
        </h1>
        <div dangerouslySetInnerHTML={{ __html: html }} className="shiki-container" />  
      </div>
    );
  } 
}

export default async function RepositoryFilePage({ params }: Props) {
  const { organization: organization_encoded, repository: repository_encoded, filepath: filepath_encoded } = await params;
  const user = await getUserFromSessionToken();

  if (!user) {
    return <ErrorScreen title="Unauthorized" message="You must be logged in to access this repository" />;
  }

  const organization = decodeURIComponent(organization_encoded);
  const repository = decodeURIComponent(repository_encoded);

  const filepath = filepath_encoded.map(s => decodeURIComponent(s));

  const repo = await getRepository(
    organization,
    repository
  );


  if (!repo) {
    return <ErrorScreen title="Not Found" message="Repository not found" />;
  }

  if (!await hasAccess(repo.id, user.id)) {
    return (
      <ErrorScreen
        title="Access Denied"
        message={`You are not allowed to access ${repo.name} repository (id: ${repo.id})`}
      />
    );
  }


  const full_filepath = filepath.join("/");

  await prepareWorkingTree(organization, repository);
  const file_exists = await exists(organization, repository, full_filepath);
  const is_folder = await isFolder(organization, repository, full_filepath);

  const folder_path = is_folder
    ? full_filepath
    : filepath.slice(0, -1).join("/");

  
  const folder_contents = await getFolders(organization, repository, folder_path);

  return (
    <div className="grid flex-1 grid-cols-[400px_1fr] overflow-hidden">
      <div className="flex flex-col overflow-y-auto border-r-4 border-sleek-details">
        <h1 className="text-xl font-semibold px-4 py-2 border-b-2 border-sleek-details sticky top-0 bg-sleek-background">
          <Link
            href={`/${organization}/${repository}`}
            className="hover:underline"
          >
            {organization}/{repository}
          </Link>
        </h1>

        <FileList
          objects={folder_contents}
          organization={organization}
          repository={repository}
          currentPath={folder_path.split("/")}
        />
      </div>
      <div className="flex flex-col flex-1 overflow-y-auto">
        {!is_folder ? (
          file_exists ? (
            <FilePreview
              file_content={await getFileContent(
                organization,
                repository,
                full_filepath
              )}
              filepath={filepath}
            />
          ) : (
            <ErrorScreen title="Not Found" message="File not found" />
          )
        ) : null}
      </div>
    </div>
  );
}
