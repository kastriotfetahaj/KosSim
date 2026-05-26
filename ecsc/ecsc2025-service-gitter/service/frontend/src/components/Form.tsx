import React from "react";

export interface FormField {
    name: string;
    label: string;
    type: "text" | "password" | "email" | "textarea";
    placeholder?: string;
    required?: boolean;
    description?: string;
    rows?: number; // for textarea
    validation?: (value: string) => string | undefined;
}

export interface FormProps {
    title: string;
    fields: FormField[];
    submitText: string;
    onSubmit: (data: Record<string, string>) => Promise<void> | void;
    error?: string;
    isLoading?: boolean;
    footer?: React.ReactNode;
    className?: string;
}

export function Form({
    title,
    fields,
    submitText,
    onSubmit,
    error,
    isLoading = false,
    footer,
    className = "",
}: FormProps) {
    const [formData, setFormData] = React.useState<Record<string, string>>(
        Object.fromEntries(fields.map((field) => [field.name, ""]))
    );
    const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});

    const handleChange = (name: string, value: string) => {
        setFormData((prev) => ({ ...prev, [name]: value }));

        if (fieldErrors[name]) {
            setFieldErrors((prev) => ({ ...prev, [name]: "" }));
        }
    };

    const validateForm = () => {
        const errors: Record<string, string> = {};

        fields.forEach((field) => {
            const value = formData[field.name];

            if (field.required && !value.trim()) {
                errors[field.name] = `${field.label} is required`;
                return;
            }

            if (field.validation && value) {
                const validationError = field.validation(value);
                if (validationError) {
                    errors[field.name] = validationError;
                }
            }
        });

        return errors;
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        const errors = validateForm();
        setFieldErrors(errors);

        if (Object.keys(errors).length > 0) {
            return;
        }

        await onSubmit(formData);
      
    };

    return (
        <div className={`w-full max-w-md bg-sleek-background p-8 shadow-md ${className}`}>
            <h1 className="mb-6 text-2xl font-bold text-center text-white">{title}</h1>

            {error && (
                <div className="mb-4 p-3 text-red-400 bg-red-900/20 border border-red-800 rounded">
                    {error}
                </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
                {fields.map((field) => (
                    <FormFieldComponent
                        key={field.name}
                        field={field}
                        value={formData[field.name]}
                        error={fieldErrors[field.name]}
                        onChange={(value) => handleChange(field.name, value)}
                        disabled={isLoading}
                    />
                ))}

                <button
                    type="submit"
                    disabled={isLoading}
                    className="w-full btn disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {isLoading ? "Loading..." : submitText}
                </button>
            </form>

            {footer && <div className="mt-4">{footer}</div>}
        </div>
    );
}

// Individual form field component
interface FormFieldComponentProps {
    field: FormField;
    value: string;
    error?: string;
    onChange: (value: string) => void;
    disabled?: boolean;
}

function FormFieldComponent({
    field,
    value,
    error,
    onChange,
    disabled = false,
}: FormFieldComponentProps) {
    const inputClasses = `mt-1 block w-full ${error ? "border-red-500 focus:border-red-500" : ""}`;
    const textareaClasses = `${inputClasses} ${field.name === "publicKey" ? "font-mono text-sm" : ""}`;

    return (
        <div>
            <label htmlFor={field.name} className="text-white">
                {field.label}
                {field.description && (
                    <span className="text-xs text-slate-400 ml-1">
                        {field.description}
                    </span>
                )}
            </label>

            {field.type === "textarea" ? (
                <textarea
                    id={field.name}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    className={textareaClasses}
                    placeholder={field.placeholder}
                    required={field.required}
                    disabled={disabled}
                    rows={field.rows || 4}
                />
            ) : (
                <input
                    type={field.type}
                    id={field.name}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    className={inputClasses}
                    placeholder={field.placeholder}
                    required={field.required}
                    disabled={disabled}
                />
            )}

            {error && (
                <p className="mt-1 text-sm text-red-400">{error}</p>
            )}
        </div>
    );
}

export const createFormFields = {
    username: (required = true): FormField => ({
        name: "username",
        label: "Username",
        type: "text",
        required,
        validation: (value) => {
            if (value && !/^[a-zA-Z0-9_-]+$/.test(value)) {
                return "Username can only contain letters, numbers, underscores, and hyphens";
            }
        },
    }),

    password: (required = true): FormField => ({
        name: "password",
        label: "Password",
        type: "password",
        required,
        validation: (value) => {
            if (value && value.length < 6) {
                return "Password must be at least 6 characters long";
            }
        },
    }),

    confirmPassword: (): FormField => ({
        name: "confirmPassword",
        label: "Confirm Password",
        type: "password",
        required: true,
    }),

    repositoryName: (): FormField => ({
        name: "name",
        label: "Name",
        type: "text",
        description: "[-._a-zA-Z0-9]",
        required: true,
        validation: (value) => {
            if (value && !/^[-._a-zA-Z0-9]+$/.test(value)) {
                return "Repository name can only contain letters, numbers, dots, underscores, and hyphens";
            }
        },
    }),

    publicDescription: (): FormField => ({
        name: "publicDescription",
        label: "Public description",
        type: "text",
        required: false,
    }),

    privateDescription: (): FormField => ({
        name: "privateDescription",
        label: "Private description",
        type: "text",
        required: false,
    }),

    sshPublicKey: (): FormField => ({
        name: "publicKey",
        label: "SSH Public Key",
        type: "textarea",
        placeholder: "ssh-rsa AAAAB3NzaC1yc2E...",
        required: true,
        rows: 4,
    }),
}; 