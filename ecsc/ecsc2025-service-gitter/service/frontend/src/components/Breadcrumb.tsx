'use client'

import Link from 'next/link';
import { usePathname } from 'next/navigation';

interface BreadcrumbItem {
    name: string;
    href: string;
    isCurrent?: boolean;
}

export function Breadcrumb() {
    const pathname = usePathname();
    const segments = pathname.split('/').filter(Boolean);

    const items: BreadcrumbItem[] = [{ name: 'Overview', href: '/' }];
    let currentPath = '';
    segments.forEach((segment, index) => {
        currentPath += `/${segment}`;
        const isLast = index === segments.length - 1;
        items.push({
            name: decodeURIComponent(segment),
            href: currentPath,
            isCurrent: isLast,
        });
    });

    return (
        <nav aria-label="Breadcrumb" className="p-4 px-6 border-b border-sleek-details bg-sleek-details-subtle">
            <ol className="flex items-center space-x-2 text-sm text-gray-500">
                {items.map((item, index) => (
                    <li key={item.href} className="flex items-center">
                        {index > 0 && <span className="mx-2">/</span>}
                        {item.isCurrent ? (
                            <span className="font-semibold text-gray-300">{item.name}</span>
                        ) : (
                            <Link href={item.href} className="hover:text-sleek-details hover:underline">
                                {item.name}
                            </Link>
                        )}
                    </li>
                ))}
            </ol>
        </nav>
    );
} 
