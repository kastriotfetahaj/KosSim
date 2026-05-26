import { Pool } from 'pg'
import fs from 'fs'

const password = process.env['POSTGRESS_PASSWORD'];

const db = new Pool({
    user: 'postgres',
    password,
    host: 'postgres',
    port: 5432,
    database: 'postgres'
})

export default db
