import React from "react";

type SettingsCardProps = {
  title: string;
  children: React.ReactNode;
};

export function SettingsCard({ title, children }: SettingsCardProps) {
  return (
    <div className="bg-sleek-fill shadow-lg border border-sleek-details">
      <h2 className="text-lg font-semibold p-2 border-b border-sleek-details pb-2">
        {title}
      </h2>
      <div className="p-4">
        {children}
      </div>
    </div>
  );
} 