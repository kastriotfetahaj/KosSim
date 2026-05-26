interface RepoLogoProps {
    repository: {
        name: string;
        logo?: string | null;
    };
    size?: 'small' | 'medium' | 'large';
    className?: string;
}

const sizeClasses = {
    small: 'w-8 h-8 text-xs',
    medium: 'w-12 h-12 text-sm',
    large: 'w-16 h-16 text-lg'
};

export function RepoLogo({ repository, size = 'medium', className = '' }: RepoLogoProps) {
    const sizeClass = sizeClasses[size];

    if (repository.logo) {
        return (
            <img
                src={repository.logo}
                alt={`${repository.name} logo`}
                className={`${sizeClass} rounded-lg object-cover border-2 border-sleek-details flex-shrink-0 ${className}`}
            />
        );
    }

    return (
        <div className={`${sizeClass} rounded-lg bg-gray-700 border-2 border-sleek-details flex items-center justify-center flex-shrink-0 ${className}`}>
            <span className="text-gray-400 font-mono font-semibold">
                {repository.name.charAt(0).toUpperCase()}
            </span>
        </div>
    );
} 