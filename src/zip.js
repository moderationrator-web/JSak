// Minimal ZIP writer (stored entries, no compression). Runs in Node and the browser,
// so the CLI and the app's own "Download app" button produce the same archive.

const CRC_TABLE = new Uint32Array(256).map((_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c;
});

function crc32(bytes) {
  let c = 0xffffffff;
  for (const b of bytes) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

// files: [{ name, data: string | Uint8Array }]; names use forward slashes.
export function createZip(files, date = new Date()) {
  const enc = new TextEncoder();
  const dosTime = (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1);
  const dosDate = ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  const locals = [];
  const centrals = [];
  let offset = 0;

  for (const file of files) {
    const name = enc.encode(file.name);
    const data = typeof file.data === 'string' ? enc.encode(file.data) : file.data;
    const crc = crc32(data);

    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true); // version needed
    local.setUint16(6, 0x0800, true); // UTF-8 names
    local.setUint16(8, 0, true); // stored
    local.setUint16(10, dosTime, true);
    local.setUint16(12, dosDate, true);
    local.setUint32(14, crc, true);
    local.setUint32(18, data.length, true);
    local.setUint32(22, data.length, true);
    local.setUint16(26, name.length, true);
    locals.push(new Uint8Array(local.buffer), name, data);

    const central = new DataView(new ArrayBuffer(46));
    central.setUint32(0, 0x02014b50, true);
    central.setUint16(4, 0x031e, true); // made by: Unix, spec 3.0
    central.setUint16(6, 20, true);
    central.setUint16(8, 0x0800, true);
    central.setUint16(10, 0, true);
    central.setUint16(12, dosTime, true);
    central.setUint16(14, dosDate, true);
    central.setUint32(16, crc, true);
    central.setUint32(20, data.length, true);
    central.setUint32(24, data.length, true);
    central.setUint16(28, name.length, true);
    central.setUint32(38, (0o100644 << 16) >>> 0, true); // regular file, rw-r--r--
    central.setUint32(42, offset, true);
    centrals.push(new Uint8Array(central.buffer), name);

    offset += 30 + name.length + data.length;
  }

  const centralSize = centrals.reduce((s, b) => s + b.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true);
  end.setUint16(10, files.length, true);
  end.setUint32(12, centralSize, true);
  end.setUint32(16, offset, true);

  const parts = [...locals, ...centrals, new Uint8Array(end.buffer)];
  const out = new Uint8Array(parts.reduce((s, b) => s + b.length, 0));
  let pos = 0;
  for (const p of parts) {
    out.set(p, pos);
    pos += p.length;
  }
  return out;
}

export const HOW_TO_OPEN = `Wallet Scout
============

Wallet Scout runs in your web browser. There is nothing to install.

WINDOWS
1. Right-click WalletScout.zip and choose "Extract All...", then click Extract.
2. Open the extracted Wallet Scout folder and double-click Wallet Scout.html.
3. If Windows asks how to open it, choose Microsoft Edge or Google Chrome.
Tip: right-click Wallet Scout.html > Send to > Desktop (create shortcut) for a desktop icon.

MAC
1. Double-click WalletScout.zip. A Wallet Scout folder appears next to it.
2. Open the folder and double-click Wallet Scout.html. It opens in Safari or your default browser.
3. If it opens in a text editor instead, right-click Wallet Scout.html > Open With > Safari (or Chrome).
Tip: drag Wallet Scout.html to the right side of the Dock for one-click access.

FIRST SCAN
1. Get a free API key at https://dashboard.helius.dev and paste it into the app.
2. Pick "Winning tokens" and paste token mint addresses (one per line),
   or pick "Wallet list" and paste wallets you want to check.
3. Click Run scan.

The app opens on demo data. Those wallets are made up and are clearly labeled.
Your API key is saved only in your own browser.
`;

export function buildAppZip(html) {
  return createZip([
    { name: 'Wallet Scout/Wallet Scout.html', data: html },
    { name: 'Wallet Scout/How to open.txt', data: HOW_TO_OPEN.replace(/\n/g, '\r\n') },
  ]);
}
