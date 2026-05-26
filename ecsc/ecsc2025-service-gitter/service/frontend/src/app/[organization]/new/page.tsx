"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { createRepositoryForLoggedInUser } from "@/lib/repos";
import { Form, createFormFields } from "@/components/Form";

export default function CreateNewRepositoryPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const { organization } = useParams();

  const formFields = [
    createFormFields.repositoryName(),
    createFormFields.publicDescription(),
    createFormFields.privateDescription(),
  ];

  const handleSubmit = async (data: Record<string, string>) => {
    setIsLoading(true);
    setError("");

      const result = await createRepositoryForLoggedInUser({
        name: data.name,
        public_description: data.publicDescription,
        private_description: data.privateDescription,
      });
      if (result.error) {
        setError(result.error);
      } else {
        router.push(`/${organization}`);
      }
      setIsLoading(false);
  };

  return (
    <div className="flex items-center justify-center bg-sleek-details-subtle min-w-full">
      <Form
        title={`Create new repository for ${organization}`}
        fields={formFields}
        submitText="Create Repository"
        onSubmit={handleSubmit}
        error={error}
        isLoading={isLoading}
      />
    </div>
  );
}
