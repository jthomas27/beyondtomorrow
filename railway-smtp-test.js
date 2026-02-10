const nodemailer = require('nodemailer');
const net = require('net');
const tls = require('tls');

const HOST = 'smtp.hostinger.com';
const PORT = 465;
const USER = process.env.mail__options__auth__user || 'admin@beyondtomorrow.world';
const PASS = process.env.mail__options__auth__pass || '';

async function testTCPPort(host, port, timeout = 10000) {
  return new Promise((resolve) => {
    const socket = tls.connect({ host, port, timeout }, () => {
      const cipher = socket.getCipher();
      socket.destroy();
      resolve({ ok: true, cipher: cipher?.name });
    });
    socket.on('error', (err) => {
      socket.destroy();
      resolve({ ok: false, error: err.message });
    });
    socket.on('timeout', () => {
      socket.destroy();
      resolve({ ok: false, error: 'TIMEOUT' });
    });
  });
}

async function main() {
  console.log('=== Railway SMTP Test ===');
  console.log(`Host: ${HOST}:${PORT}`);
  console.log(`User: ${USER}`);
  console.log(`Pass: ${PASS ? '****' + PASS.slice(-4) : '(not set)'}`);
  console.log(`Date: ${new Date().toISOString()}`);
  console.log('');

  // Step 1: TCP/TLS connectivity
  console.log('[1/3] Testing TCP/TLS connectivity to smtp.hostinger.com:465...');
  const tcp = await testTCPPort(HOST, PORT);
  if (tcp.ok) {
    console.log(`  ✅ TCP/TLS connected! Cipher: ${tcp.cipher}`);
  } else {
    console.log(`  ❌ TCP/TLS failed: ${tcp.error}`);
    console.log('');
    console.log('⚠️  SMTP port 465 is still blocked. Railway Pro SMTP may need');
    console.log('   a redeploy to take effect. Check Railway dashboard.');
    process.exit(1);
  }

  // Step 2: SMTP auth
  console.log('[2/3] Verifying SMTP authentication...');
  const transporter = nodemailer.createTransport({
    host: HOST,
    port: PORT,
    secure: true,
    auth: { user: USER, pass: PASS },
    connectionTimeout: 15000,
    socketTimeout: 15000,
  });

  try {
    await transporter.verify();
    console.log('  ✅ SMTP authentication verified!');
  } catch (err) {
    console.log(`  ❌ SMTP auth failed: ${err.message}`);
    process.exit(1);
  }

  // Step 3: Send test email
  console.log('[3/3] Sending test email from Railway...');
  try {
    const info = await transporter.sendMail({
      from: `"BeyondTomorrow.World" <${USER}>`,
      to: USER,
      subject: `✅ Railway SMTP Test — ${new Date().toISOString()}`,
      text: [
        'SMTP is working from Railway!',
        '',
        `Sent at: ${new Date().toISOString()}`,
        'From: Railway (Ghost service)',
        `SMTP Host: ${HOST}:${PORT}`,
        `Cipher: ${tcp.cipher}`,
        '',
        'Railway Pro plan SMTP ports are unblocked.',
        'Ghost CMS can now send emails.',
      ].join('\n'),
      html: `
        <h2>✅ Railway SMTP Test Successful</h2>
        <p>SMTP is working from <strong>Railway</strong>!</p>
        <table style="border-collapse:collapse; margin-top:12px;">
          <tr><td style="padding:4px 12px; border:1px solid #ddd;"><strong>Sent at</strong></td>
              <td style="padding:4px 12px; border:1px solid #ddd;">${new Date().toISOString()}</td></tr>
          <tr><td style="padding:4px 12px; border:1px solid #ddd;"><strong>From</strong></td>
              <td style="padding:4px 12px; border:1px solid #ddd;">Railway (Ghost service)</td></tr>
          <tr><td style="padding:4px 12px; border:1px solid #ddd;"><strong>SMTP Host</strong></td>
              <td style="padding:4px 12px; border:1px solid #ddd;">${HOST}:${PORT}</td></tr>
          <tr><td style="padding:4px 12px; border:1px solid #ddd;"><strong>TLS Cipher</strong></td>
              <td style="padding:4px 12px; border:1px solid #ddd;">${tcp.cipher}</td></tr>
        </table>
        <p style="margin-top:16px; color:#888;">Railway Pro plan — SMTP ports unblocked. Ghost CMS can now send emails.</p>
      `
    });

    console.log('  ✅ Email sent from Railway!');
    console.log(`  Message ID: ${info.messageId}`);
    console.log(`  Accepted: ${info.accepted.join(', ')}`);
    console.log('');
    console.log('🎉 SUCCESS — Railway Pro SMTP is fully working!');
    console.log('📬 Check admin@beyondtomorrow.world inbox.');
  } catch (err) {
    console.log(`  ❌ Send failed: ${err.message}`);
    process.exit(1);
  }
}

main();
