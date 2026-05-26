'use server'

import bcrypt from 'bcrypt';
import db from './db';
import fs from 'fs';
import { SSH_AUTHORIZED_KEYS_DIRECTORY, SSH_AUTHORIZED_KEYS_FILE } from '../constants';

const SSH_KEY_REGEX = /^[-a-z0-9]+ [-A-Za-z0-9+/]+={0,3}( .+)?$/;
const USER_REGEX = /^[-._a-zA-Z0-9]+$/;


async function writeKey(username: string, public_key: string) {
    const file = SSH_AUTHORIZED_KEYS_FILE();

    await fs.promises.mkdir(SSH_AUTHORIZED_KEYS_DIRECTORY, { recursive: true });

    const entry = `${public_key} ${username}\n`;

    await fs.promises.appendFile(file, entry);
}

export async function getUser(username: string) {
    const result = await db.query(
        'SELECT id, username, password_hash FROM users WHERE username = $1',
        [username]
    );
    return result.rows[0] || null;
}

export async function verifyUserPassword(password: string, passwordHash: string) {
    return await bcrypt.compare(password, passwordHash);
}



export async function createUser(username: string, password: string, publicKey: string) {

    if (!USER_REGEX.test(username)) {
        throw new Error('Invalid username');
    }

    if (!SSH_KEY_REGEX.test(publicKey)) {
        throw new Error('Invalid public key');
    }

    if (username.length < 6) {
        throw new Error('Username must be at least 6 characters long');
    }

    if (password.length < 6) {
        throw new Error('Password must be at least 6 characters long');
    }

    const existingUser = await getUser(username);
    if (existingUser) {
        throw new Error('Username already exists');
    }

    const saltRounds = 10;
    const passwordHash = await bcrypt.hash(password, saltRounds);


    const shortKey = publicKey.split(' ').slice(0, 2).join(' ');

    const result = await db.query(
        'INSERT INTO users (username, password_hash, public_key) VALUES ($1, $2, $3) RETURNING id, username',
        [username, passwordHash, shortKey]
    );

    const user = result.rows[0];

    await writeKey(username, shortKey);

    return user;
}

export async function searchUsersByPrefix(prefix: string): Promise<{ id: string; username: string }[]> {
    if (prefix.length < 4) {
        return [];
    }
    
    const result = await db.query(
        'SELECT id, username FROM users WHERE username ILIKE $1 LIMIT 10',
        [prefix + '%']
    );
    
    return result.rows;
}




