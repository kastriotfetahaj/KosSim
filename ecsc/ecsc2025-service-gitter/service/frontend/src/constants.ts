


export const USER_BASE_DIRECTORY = "/home/node";
export const GIT_BASE_DIRECTORY = `${USER_BASE_DIRECTORY}/git`;

// Authorized keys file rotates every 5 minutes
const CURRENT_TIMESTAMP = () => Math.floor(new Date().getTime() / 1000 / 60 / 5);
export const SSH_AUTHORIZED_KEYS_DIRECTORY = `${GIT_BASE_DIRECTORY}/.gitter-keys`;
export const SSH_AUTHORIZED_KEYS_FILE = () => `${GIT_BASE_DIRECTORY}/.gitter-keys/authorized_keys-${CURRENT_TIMESTAMP()}`;
export const GIT_REPOSITORIES_DIRECTORY = `${GIT_BASE_DIRECTORY}/repositories`;




