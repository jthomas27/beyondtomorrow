const mysql = require('mysql2/promise');

async function testMySQLConnection() {
  // Use public URL for local testing, internal URL is for service-to-service
  const connectionString = process.env.MYSQL_URL || process.env.MYSQL_PUBLIC_URL;

  if (!connectionString) {
    console.error('✗ MYSQL_URL or MYSQL_PUBLIC_URL environment variable not set');
    process.exit(1);
  }

  let connection;
  try {
    // Connect to MySQL
    connection = await mysql.createConnection(connectionString);
    console.log('✓ MySQL connection successful!');

    // Get MySQL version
    const [versionRows] = await connection.query('SELECT VERSION() as version');
    console.log(`✓ MySQL Version: ${versionRows[0].version}`);

    // Show databases
    const [dbRows] = await connection.query('SHOW DATABASES');
    const databases = dbRows.map(r => r.Database).join(', ');
    console.log(`✓ Databases: ${databases}`);

    // Check current database
    const [currentDb] = await connection.query('SELECT DATABASE() as db');
    console.log(`✓ Current database: ${currentDb[0].db}`);

    // Show tables (Ghost creates these on first boot)
    const [tableRows] = await connection.query('SHOW TABLES');
    if (tableRows.length > 0) {
      const tableKey = Object.keys(tableRows[0])[0];
      const tables = tableRows.map(r => r[tableKey]);
      console.log(`✓ Tables (${tables.length}): ${tables.join(', ')}`);
    } else {
      console.log('⚠ No tables yet — Ghost will create them on first startup');
    }

    // Test Ghost connection variables match
    console.log('\n── Ghost → MySQL Configuration Check ──');
    const host = process.env.database__connection__host || '(not set)';
    const port = process.env.database__connection__port || '(not set)';
    const user = process.env.database__connection__user || '(not set)';
    const db = process.env.database__connection__database || '(not set)';
    const client = process.env.database__client || '(not set)';
    console.log(`  database__client:              ${client}`);
    console.log(`  database__connection__host:     ${host}`);
    console.log(`  database__connection__port:     ${port}`);
    console.log(`  database__connection__user:     ${user}`);
    console.log(`  database__connection__database: ${db}`);

    const internalHost = 'mysql.railway.internal';
    if (host === internalHost) {
      console.log(`✓ Host correctly set to internal Railway address`);
    } else if (host === '(not set)') {
      console.log(`⚠ Ghost connection vars not in this environment (expected when testing from MySQL service)`);
    } else {
      console.log(`✗ Host should be "${internalHost}" but is "${host}"`);
    }

    console.log('\n✓ MySQL test complete!');
  } catch (err) {
    console.error(`✗ MySQL connection failed: ${err.message}`);
    process.exit(1);
  } finally {
    if (connection) await connection.end();
  }
}

testMySQLConnection();
