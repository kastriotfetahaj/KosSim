const express = require("express");
import { sql } from "bun";

const app = express();
const port = 3000;
app.use(express.json());

const SSH_KEY_REGEX = /^ssh-[-a-z0-9]+ [-A-Za-z0-9+/]+={0,3}( .+)?$/;
const USER_REGEX = /^[-._a-zA-Z0-9]+$/;
const REPOSITORY_REGEX = /^[-._a-zA-Z0-9]+$/;


app.get("/identify/:pubkey", async (req, res) => {
    const pubkey = req.params.pubkey.trim();

    const user = await sql`SELECT * FROM users WHERE public_key = ${pubkey}`;

    if (user.length === 0) {
        res.status(404);
        res.send("User not found");
        return;
    }

    res.status(200);
    res.send(user[0].username);
});

app.get("/get-repositories", async (req, res) => {
    const user = req.query.user;

    const repositories = await sql`
SELECT name, public_description, private_description, owner.username
FROM repositories
JOIN repository_access
  ON repository_id = repositories.id
JOIN users AS login
  ON user_id = login.id
JOIN users AS owner
  ON owner_id = owner.id

WHERE login.username = ${user}`;

    for (let repo of repositories) {
	repo["name"] = `${repo["username"]}/${repo["name"]}`;
    }

    res.status(200);
    res.send(JSON.stringify(repositories))
});

app.listen(port, '0.0.0.0', () => {
    console.log(`Backend started on port ${port}!`);
});
