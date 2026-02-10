const nodemailer = require('nodemailer');

const transporter = nodemailer.createTransport({
  host: 'smtp.hostinger.com',
  port: 465,
  secure: true,
  auth: {
    user: 'admin@beyondtomorrow.world',
    pass: 'SilverArrows1!'
  },
  connectionTimeout: 15000,
  socketTimeout: 15000,
});

async function test() {
  console.log('--- SMTP Connection Test ---');
  console.log('Host: smtp.hostinger.com:465');
  console.log('User: admin@beyondtomorrow.world');
  console.log('');

  // Step 1: Verify SMTP connection
  console.log('[1/2] Verifying SMTP connection...');
  try {
    await transporter.verify();
    console.log('  ✅ SMTP connection verified successfully!');
  } catch (err) {
    console.error('  ❌ SMTP connection failed:', err.message);
    process.exit(1);
  }

  // Step 2: Send test email
  console.log('[2/2] Sending test email...');
  try {
    const info = await transporter.sendMail({
      from: '"BeyondTomorrow.World" <admin@beyondtomorrow.world>',
      to: 'admin@beyondtomorrow.world',
      subject: `✅ SMTP Test — ${new Date().toISOString()}`,
      text: `This is a test email from BeyondTomorrow.World.\n\nSent at: ${new Date().toISOString()}\nFrom: Local machine (smtp-test.js)\nSMTP Host: smtp.hostinger.com:465\n\nIf you received this, SMTP is working correctly.`,
      html: `
        <h2>✅ SMTP Test Successful</h2>
        <p>This is a test email from <strong>BeyondTomorrow.World</strong>.</p>
        <table style="border-collapse:collapse; margin-top:12px;">
          <tr><td style="padding:4px 12px; border:1px solid #ddd;"><strong>Sent at</strong></td><td style="padding:4px 12px; border:1px solid #ddd;">${new Date().toISOString()}</td></tr>
          <tr><td style="padding:4px 12px; border:1px solid #ddd;"><strong>From</strong></td><td style="padding:4px 12px; border:1px solid #ddd;">Local machine (smtp-test.js)</td></tr>
          <tr><td style="padding:4px 12px; border:1px solid #ddd;"><strong>SMTP Host</strong></td><td style="padding:4px 12px; border:1px solid #ddd;">smtp.hostinger.com:465</td></tr>
        </table>
        <p style="margin-top:16px; color:#666;">If you received this, SMTP is working correctly.</p>
      `
    });

    console.log('  ✅ Test email sent!');
    console.log('  Message ID:', info.messageId);
    console.log('  Accepted:', info.accepted.join(', '));
    if (info.rejected.length > 0) {
      console.log('  Rejected:', info.rejected.join(', '));
    }
    console.log('');
    console.log('📬 Check admin@beyondtomorrow.world inbox for the test email.');
  } catch (err) {
    console.error('  ❌ Failed to send email:', err.message);
    process.exit(1);
  }
}

test();
