"use client";

import { useState } from "react";
import { updateRepositoryLogo } from "@/lib/repos";
import LogoCropper from "./LogoCropper";

interface Repository {
    id: string;
    name: string;
    owner_id: string;
    public_description: string | null;
    private_description: string | null;
    logo: string | null;
}

interface RepositorySettingsProps {
    repository: Repository;
    organization: string;
}

export default function RepositorySettings({ repository, organization }: RepositorySettingsProps) {
    const [isUpdating, setIsUpdating] = useState(false);
    const [error, setError] = useState("");
    const [success, setSuccess] = useState("");

    const handleLogoUpdate = async (croppedImageBase64: string) => {
        setIsUpdating(true);
        setError("");
        setSuccess("");
        try {
            await updateRepositoryLogo(organization, repository.name, croppedImageBase64);
            setSuccess("Logo updated successfully!");
        } catch (err) {
            setError(err instanceof Error ? err.message : "An error occurred while updating logo");
        } finally {
            setIsUpdating(false);
        }
    };

    return (
        <div className="space-y-6">
            <div className="">
                <LogoCropper
                    onCropComplete={handleLogoUpdate}
                    initialImage={repository.logo || undefined}
                    className="w-full"
                />

                {error && (
                    <div className="text-red-400 text-sm mt-2 p-2 bg-sleek-background border border-sleek-details">
                        {error}
                    </div>
                )}

                {success && (
                    <div className="text-green-400 text-sm mt-2 p-2 bg-sleek-background border border-sleek-details">
                        {success}
                    </div>
                )}

                {isUpdating && (
                    <div className="text-cyan text-sm mt-2 p-2 bg-sleek-background border border-sleek-details">
                        Updating logo...
                    </div>
                )}
            </div>
        </div>
    );
} 