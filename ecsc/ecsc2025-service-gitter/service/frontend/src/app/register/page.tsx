"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { register } from "@/lib/auth";
import { Form, createFormFields, FormField } from "@/components/Form";

export default function RegisterPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const formFields: FormField[] = [
    createFormFields.username(),
    createFormFields.password(),
    createFormFields.confirmPassword(),
    createFormFields.sshPublicKey(),
  ];

  const handleSubmit = async (data: Record<string, string>) => {
    setIsLoading(true);
    setError("");

    if (data.password !== data.confirmPassword) {
      setError("Passwords do not match");
      setIsLoading(false);
      return;
    }

    try {
      const result = await register(data.username, data.password, data.publicKey);
      if (result.error) {
        setError(result.error);
      } else {
        router.push("/login");
      }
    } catch (err) {
      setError("An error occurred during registration");
    } finally {
      setIsLoading(false);
    }
  };

  const footer = (
    <p className="text-center text-sm text-sleek-details-subtle">
      Already have an account?{" "}
      <Link href="/login" className="text-sleek-details hover:underline">
        Login here
      </Link>
    </p>
  );

  return (
    <div className="flex items-center justify-center bg-sleek-details-subtle min-w-full">
      <Form
        title="Create an Account"
        fields={formFields}
        submitText="Register"
        onSubmit={handleSubmit}
        error={error}
        isLoading={isLoading}
        footer={footer}
      />
    </div>
  );
}
