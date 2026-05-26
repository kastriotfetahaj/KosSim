import { getDefaultFileForRepository } from "@/lib/repos";
import { redirect } from "next/navigation";


type Props = {
    params: Promise<{
      organization: string;
      repository: string;
    }>;
  };

  
export default async function TreePage({ params }: Props) {

    const { organization, repository } = await params;
    
    const defaultFile = await getDefaultFileForRepository(organization, repository);

    if (defaultFile) {
        redirect(`/${organization}/${repository}/tree/${defaultFile}`);
    }

    redirect(`/${organization}/${repository}/`);
}
