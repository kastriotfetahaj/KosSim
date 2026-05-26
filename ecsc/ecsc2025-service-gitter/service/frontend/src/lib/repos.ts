'use server'


import db from "./db";
import fs from 'fs';
import { exec } from 'child_process';
import path from 'path';
import { GIT_REPOSITORIES_DIRECTORY } from "../constants";
import { execAsync } from "./util";
import { getUserFromSessionToken } from "./auth";
export type Repository = {
    id: string;
    name: string;
    owner_id: string;
    public_description: string | null;
    private_description: string | null;
    logo: string | null;
    owner_username: string;
}


const REPOSITORY_REGEX = /^[-._a-zA-Z0-9]+$/;


export async function getRepository(username: string, repository_name: string): Promise<Repository | null> {
    const result = await db.query(
        `SELECT r.id, r.name, r.public_description, r.private_description, r.logo, r.owner_id FROM repositories r JOIN users u
         ON r.owner_id = u.id WHERE u.username = $1 AND r.name = $2`,
        [username, repository_name]
    );
    return result.rows[0];
}


export async function isOwner(repository_id: string, user_id: string): Promise<boolean> {
    const result = await db.query('SELECT role FROM repository_access WHERE repository_id = $1 AND user_id = $2', [repository_id, user_id]);
    return result.rows.length > 0 && result.rows[0].role === 'owner';
}


async function getOwnerId(): Promise<string> {
    const user = await getUserFromSessionToken();
    if (!user) {
        throw new Error('User not found');
    }

    return user.id;
}


export async function addContributor(repository_id: string, user_id: string, owner?: string): Promise<{error?: string}> {   
    const owner_id = owner ?? await getOwnerId();

    if (owner_id === user_id) {
        return {error: 'Cannot add yourself as a contributor'};
    }



    // check if user is owner
    if (!await isOwner(repository_id, owner_id)) {
        return {error: 'Access denied'};
    }

    await db.query(
        'INSERT INTO repository_access (repository_id, user_id, role) VALUES ($1, $2, $3)',
        [repository_id, user_id, 'contributor']
    );

    return {error: undefined};
}

export async function removeContributor(repository_id: string, user_id: string, owner?: string): Promise<void> {

    const owner_id = owner ?? await getOwnerId();


    // check if user is owner
    if (!await isOwner(repository_id, owner_id)) {
        throw new Error('Access denied');
    }

    await db.query(
        'DELETE FROM repository_access WHERE repository_id = $1 AND user_id = $2',
        [repository_id, user_id]
    );
}

export async function getRepositoryMembers(repository_id: string) {
    const user = await getUserFromSessionToken();
    if (!user) {
        return [];
    }

    // check if user is owner
    const access_check = await db.query('SELECT role FROM repository_access WHERE repository_id = $1 AND user_id = $2', [repository_id, user.id]);
    if (access_check.rows.length === 0 || (access_check.rows[0].role !== 'owner' && access_check.rows[0].role !== 'contributor')) {
        return [];
    }

    const result = await db.query(
        `SELECT u.username, ra.role, u.id as user_id
        FROM repository_access ra 
        JOIN users u ON ra.user_id = u.id 
        WHERE ra.repository_id = $1`,
        [repository_id]
    );

    return result.rows;
}

export async function hasAccess(repository_id: string, user_id: string): Promise<boolean> {
    const result = await db.query('SELECT 1 FROM repository_access WHERE repository_id = $1 AND user_id = $2', [repository_id, user_id]);
    return result.rows.length > 0;
}


export async function getRepositories(user_id: string): Promise<Repository[]> {
    if (!user_id) {
        return [];
    }

    const result = await db.query(
        `SELECT r.id, r.name, r.public_description, r.private_description, r.logo, r.owner_id, o.username as owner_username
         FROM repositories r
         JOIN repository_access ra ON r.id = ra.repository_id
         JOIN users o ON r.owner_id = o.id
         WHERE ra.user_id = $1`,
        [user_id]
    );
    return result.rows;
}


export async function organizationExists(organization: string): Promise<boolean> {
    const result = await db.query('SELECT 1 FROM users WHERE username = $1', [organization]);
    return result.rows.length > 0;
}

export async function getRepositoriesForOrganizationForUser(organization: string): Promise<Repository[]> {
    const user = await getUserFromSessionToken();
    if (!user) {
        return [];
    }

    const result = await db.query(
        `SELECT r.id, r.name, r.public_description, r.private_description, r.logo, r.owner_id, o.username as owner_username
         FROM repositories r
         JOIN repository_access ra ON r.id = ra.repository_id
         JOIN users o ON r.owner_id = o.id
         WHERE ra.user_id = $1 AND o.username = $2`,
        [user.id, organization]
    );
    return result.rows;
}


export async function createRepositoryForLoggedInUser({ name, public_description, private_description }: { name: string, public_description: string, private_description: string }): Promise<{error?: string}> {
    const user = await getUserFromSessionToken();
    if (!user) {
        return {error: 'User not found'};
    }
    return createRepository({ name, public_description, private_description, username: user.username, user_id: user.id });
}

export async function updateRepositoryLogo(username: string, repository_name: string, logo: string): Promise<void> {
    const user = await getUserFromSessionToken();
    if (!user) {
        throw new Error('User not found');
    }

    const repo = await getRepository(username, repository_name);
    if (!repo || repo.owner_id !== user.id) {
        throw new Error('Repository not found or access denied');
    }

    await db.query(
        'UPDATE repositories SET logo = $1 WHERE id = $2',
        [logo, repo.id]
    );
}

async function createRepository({ name, public_description, private_description, username, user_id }: { name: string, public_description: string, private_description: string, username: string, user_id: string }): Promise<{error?: string}> {

    if (!REPOSITORY_REGEX.test(name)) {
        return {error: 'Invalid repository name'};
    }

    const result = await db.query(
        'INSERT INTO repositories (name, public_description, private_description, logo, owner_id) VALUES ($1, $2, $3, $4, $5) RETURNING id',
        [name, public_description, private_description, null, user_id]
    );


    const repositoryId = result.rows[0].id;
    await db.query(
        'INSERT INTO repository_access (repository_id, user_id, role) VALUES ($1, $2, $3)',
        [repositoryId, user_id, 'owner']
    );

    const repoPath = path.join(GIT_REPOSITORIES_DIRECTORY, username, name);

    await fs.promises.mkdir(repoPath, { recursive: true });

    await new Promise((resolve, reject) => {
        exec('git init', { cwd: repoPath }, (error, stdout, stderr) => {
            if (error) {
                reject(error);
                return;
            }
            resolve(stdout);
        });
    });


    const readmePath = path.join(repoPath, 'README.md');
    const readmeContent = `# ${name}\n\n${public_description}`;
    await fs.promises.writeFile(readmePath, readmeContent);

    await execAsync(`git add README.md`, { cwd: repoPath });

    const args = [
        'commit', '-m', '"Initial commit"', `--author="${username} <${username}@gitter>"`
    ];

    await execAsync(`git ${args.join(' ')}`, { cwd: repoPath });

    return {error: undefined};
}


export interface GitFileOrFolder {
    name: string;
    path: string;
    size: number;
    type: string;
    modified: string | null;
}


async function getLastModified(repoPath: string, filepath: string): Promise<string | null> {
    return await new Promise<string | null>((resolve, reject) => {
        exec(`git log -1 --pretty=format:"%at" -- "${filepath}"`, { cwd: repoPath }, (error, stdout) => {
            if (error) {
                resolve(null);
                return;
            }

            // We don't do it for folders
            if (stdout === "") {
                resolve(null);
                return;
            }

            resolve(new Date(parseInt(stdout) * 1000).toISOString());
        });
    });
}


export async function getFolders(username: string, repository_name: string, filepath: string): Promise<GitFileOrFolder[]> {
    const repoPath = path.join(GIT_REPOSITORIES_DIRECTORY, username, repository_name, filepath);
    const gitOutput = await new Promise<string>((resolve, reject) => {
        exec('git ls-tree -l HEAD', { cwd: repoPath }, (error, stdout, stderr) => {
            if (error) {
                reject(error);
                return;
            }
            resolve(stdout);
        });
    });

    const files: GitFileOrFolder[] = await Promise.all(gitOutput.split('\n')
        .filter(line => line.trim().length > 0)
        .map(async (line) => {
            // Format: <mode> <type> <object> <size> <file>
            const parts = line.split(/\s+/);
            const [mode, type, object, size] = parts;
            const name = parts.slice(4).join(' ');

            return {
                name,
                path: name,
                size: parseInt(size) || 0,
                type: type === 'tree' ? 'folder' : 'file',
                modified: await getLastModified(repoPath, name)
            };
        })
    );

    if (files.length === 0) {
        return [];
    }


    return files;
}

export async function prepareWorkingTree(username: string, repository_name: string, branch: string = "master"): Promise<void> {
    return new Promise<void>((resolve, reject) => {
        exec(`git checkout -f ${branch}`, { cwd: path.join(GIT_REPOSITORIES_DIRECTORY, username, repository_name) }, (error) => {
            if (error) {
                reject(error);
                return;
            }
            resolve();
        });
    });
}

export async function getFileContent(username: string, repository_name: string, filepath: string): Promise<string> {
    const repoPath = path.join(GIT_REPOSITORIES_DIRECTORY, username, repository_name, filepath);

    return fs.promises.readFile(repoPath, 'utf8');
}
export async function isFolder(username: string, repository_name: string, filepath: string): Promise<boolean> {
    const repoPath = path.join(GIT_REPOSITORIES_DIRECTORY, username, repository_name, filepath);
    try {
        const stats = await fs.promises.stat(repoPath);
        return stats.isDirectory();
    } catch (error) {
        return false;
    }
}


export async function getDefaultFileForRepository(organisation: string, repository_name: string): Promise<string | undefined> {
    const repoPath = path.join(GIT_REPOSITORIES_DIRECTORY, organisation, repository_name);
    const files = await fs.promises.readdir(repoPath);

    // Look for README.md (case-insensitive)
    const readmeFile = files.find(
        f => f.toLowerCase() === "readme.md"
    );
    if (readmeFile) {
        return readmeFile;
    }

    // If not found, return the first file (if any)
    return files[0];
}

export async function exists(username: string, repository_name: string, filepath: string): Promise<boolean> {
    const repoPath = path.join(GIT_REPOSITORIES_DIRECTORY, username, repository_name, filepath);
    try {
        await fs.promises.stat(repoPath);
        return true;
    } catch (error) {
        return false;
    }
}
