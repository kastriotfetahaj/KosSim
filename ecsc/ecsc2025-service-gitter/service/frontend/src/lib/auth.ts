'use server'

import { cookies } from 'next/headers'
import jwt from 'jsonwebtoken'
import { getUser, verifyUserPassword, createUser } from './user'
import fs from 'fs'

const JWT_SECRET = (process.env as any)['JWT_SECRET'];


export async function login(username: string, password: string) {
    if (!username || !password) {
        throw 'Username and password are required';
    }

    try {
        const user = await getUser(username);

        if (!user) {
            return { error: 'Invalid username or password' };
        }

        const passwordMatch = await verifyUserPassword(password, user.password_hash);

        if (!passwordMatch) {
            return { error: 'Invalid username or password' };
        }

        const cookieStore = await cookies()

        const jwt_string = jwt.sign({
            id: user.id,
            username: user.username
        }, JWT_SECRET)

        cookieStore.set('session_token', jwt_string, {
            httpOnly: true,
            sameSite: 'strict' as const,
            maxAge: 7 * 24 * 60 * 60 * 1000, // 1 week
            path: '/'
        })



    } catch (error) {
        console.error('Login error:', error);
        return { error: 'Invalid username or password' };
    }
}

export async function register(username: string, password: string, publicKey: string) {
    if (!username || !password) {
        return { error: 'Username and password are required' };
    }

    try {
        const newUser = await createUser(username, password, publicKey.trim());
        return newUser;
    } catch (error) {
        console.error('Registration error:', error);
        if (error instanceof Error) {
            return { error: error.message };
        }
        return { error: 'Failed to register user' };
    }
}

export async function logout() {
    const cookieStore = await cookies();
    cookieStore.delete("session_token");
}

export interface LoggedInUser {
    id: string;
    username: string;
}

export async function getUserFromSessionToken(): Promise<LoggedInUser | null> {
    const cookieStore = await cookies();
    const session_token = cookieStore.get("session_token");

    if (!session_token) {
        return null;
    }
    try {
        const decoded = jwt.verify(session_token.value, JWT_SECRET) as { id: string, username: string };
        return decoded;
    } catch (error) {
        console.error('Error verifying session token:', error);
        return null;
    }
}
