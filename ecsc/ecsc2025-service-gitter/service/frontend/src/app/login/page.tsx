"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { login } from "@/lib/auth";
import { Form, createFormFields } from "@/components/Form";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const formFields = [
    createFormFields.username(),
    createFormFields.password(),
  ];

  const handleSubmit = async (data: Record<string, string>) => {
    setIsLoading(true);
    setError("");

    try {
      const result = await login(data.username, data.password);
      if (result?.error) {
        setError(result.error);
      } else {
        router.push("/");
      }
    } catch (err) {
      setError("An error occurred during login");
    } finally {
      setIsLoading(false);
    }
  };

  const footer = (
    <p className="text-center text-sm text-sleek-details-subtle">
      Don't have an account?{" "}
      <Link href="/register" className="text-sleek-details hover:underline">
        Register here
      </Link>
    </p>
  );

  return (
    <div className="flex items-center justify-center bg-sleek-details-subtle min-w-full">
      <Form
        title="Login to Gitter"
        fields={formFields}
        submitText="Login"
        onSubmit={handleSubmit}
        error={error}
        isLoading={isLoading}
        footer={footer}
      />
    </div>
  );
}
