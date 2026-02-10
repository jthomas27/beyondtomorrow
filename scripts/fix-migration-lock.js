const mysql = require('mysql2/promise');

async function fixMigrationLock() {
  const connectionString = process.env.MYSQL_URL || process.env.MYSQL_PUBLIC_URL;

  if (!connectionString) {
    console.error('✗ MYSQL_URL or MYSQL_PUBLIC_URL environment variable not set');
    process.exit(1);
  }

  let connection;
  try {
    connection = await mysql.createConnection(connectionString);
    console.log('✓ Connected to MySQL');

    // Check current lock state
    const [lockRows] = await connection.query('SELECT * FROM migrations_lock');
    console.log('Current migration lock state:', lockRows);

    // Release the lock
    await connection.query("UPDATE migrations_lock SET locked = 0, acquired_at = NULL WHERE lock_key = 'km01'");
    console.log('✓ Migration lock released');

    // Verify
    const [verifyRows] = await connection.query('SELECT * FROM migrations_lock');
    console.log('Updated migration lock state:', verifyRows);

    console.log('\n✓ Migration lock fix complete! Redeploy Ghost now.');
  } catch (err) {
    console.error(`✗ Failed: ${err.message}`);
    process.exit(1);
  } finally {
    if (connection) await connection.end();
  }
}

fixMigrationLock();
