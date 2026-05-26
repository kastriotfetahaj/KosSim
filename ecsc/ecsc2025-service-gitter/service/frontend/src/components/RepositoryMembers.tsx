
"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { addContributor, removeContributor, getRepositoryMembers } from "@/lib/repos";
import { searchUsersByPrefix } from "@/lib/user";

interface RepositoryMembersProps {
    repo: {
        id: string;
    };
    members: (Awaited<ReturnType<typeof getRepositoryMembers>>[number] & { user_id: number })[];
}

export default function RepositoryMembers({ repo, members }: RepositoryMembersProps) {
    const router = useRouter();
    const [error, setError] = useState("");
    const [success, setSuccess] = useState("");
    const [isAdding, setIsAdding] = useState(false);
    const [removingUserId, setRemovingUserId] = useState<string | null>(null);
    const [username, setUsername] = useState("");
    const [searchResults, setSearchResults] = useState<{ id: string; username: string }[]>([]);
    const [showDropdown, setShowDropdown] = useState(false);
    const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
    const dropdownRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        function handleClickOutside(event: MouseEvent) {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setShowDropdown(false);
            }
        }

        document.addEventListener('mousedown', handleClickOutside);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, []);

    useEffect(() => {
        const searchUsers = async () => {
            if (username.length >= 4 && !selectedUserId) {
                try {
                    const results = await searchUsersByPrefix(username);
                    setSearchResults(results);
                    setShowDropdown(true);
                } catch (err) {
                    setSearchResults([]);
                }
            } else {
                setSearchResults([]);
                setShowDropdown(false);
            }
        };

        const timeoutId = setTimeout(searchUsers, 300);
        return () => clearTimeout(timeoutId);
    }, [username, selectedUserId]);

    const handleAddContributor = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!selectedUserId) {
            setError("Please select a user from the dropdown");
            return;
        }
        
        setIsAdding(true);
        setError("");
        setSuccess("");
        try {
            const result = await addContributor(repo.id, selectedUserId);
            if (result.error) {
                setError(result.error);
            } else {
                setSuccess("Contributor added successfully!");
                setUsername("");
                setSelectedUserId(null);
                setShowDropdown(false);
                router.refresh();
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : "An error occurred");
        } finally {
            setIsAdding(false);
        }
    };

    const handleRemoveContributor = async (userId: string) => {
        if (!window.confirm("Are you sure you want to remove this contributor?")) {
            return;
        }
        setRemovingUserId(userId);
        setError("");
        setSuccess("");
        try {
            await removeContributor(repo.id, userId.toString());
            setSuccess("Contributor removed successfully!");
            router.refresh();
        } catch (err) {
            setError(err instanceof Error ? err.message : "An error occurred");
        } finally {
            setRemovingUserId(null);
        }
    };

    const handleUserSelect = (user: { id: string; username: string }) => {
        setUsername(user.username);
        setSelectedUserId(user.id);
        setSearchResults([]);
        setShowDropdown(false);
    };

    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const value = e.target.value;
        setUsername(value);
        setSelectedUserId(null);
    };

    return (
        <div className="space-y-6">
       

            
            <div className="space-y-2">
                {members.map((member) => (
                    <div key={member.username} className="flex items-center justify-between p-2">
                        <div>
                            <p className="font-bold">{member.username}</p>
                            <p className="text-sm text-slate-400">{member.role}</p>
                        </div>
                        {member.role === "contributor" && (
                            <button
                                onClick={() => handleRemoveContributor(member.user_id)}
                                disabled={isAdding || removingUserId !== null}
                                className="btn-danger"
                            >
                                {removingUserId === member.user_id ? "Removing..." : "Remove"}
                            </button>
                        )}
                    </div>
                ))}
            </div>

            <div>
                <h3 className="text-lg font-bold">Add Contributor</h3>
                <form onSubmit={handleAddContributor} className="flex items-center gap-2 mt-2">
                    <div className="relative flex-1" ref={dropdownRef}>
                        <input
                            ref={inputRef}
                            type="text"
                            value={username}
                            onChange={handleInputChange}
                            placeholder="Search for a user"
                            className="input-field w-full"
                            disabled={isAdding || removingUserId !== null}
                            autoComplete="off"
                        />
                        {showDropdown && searchResults.length > 0 && (
                            <div className="absolute z-10 w-full mt-1 bg-sleek-background border border-sleek-details shadow-lg max-h-60 overflow-y-auto">
                                {searchResults.map((user) => (
                                                                         <button
                                         key={user.id}
                                         type="button"
                                         onMouseDown={(e) => {
                                             e.preventDefault();
                                             handleUserSelect(user);
                                         }}
                                         className="w-full px-3 py-2 text-left hover:bg-slate-700 focus:bg-slate-700 focus:outline-none"
                                     >
                                        <div className="font-medium">{user.username}</div>
                                        <div className="text-sm text-slate-400">ID: {user.id}</div>
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                    <button 
                        type="submit" 
                        className="btn-primary" 
                        disabled={isAdding || removingUserId !== null || !selectedUserId}
                    >
                        {isAdding ? "Adding..." : "Add"}
                    </button>
                </form>
            </div>


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
        </div>
    );
} 
