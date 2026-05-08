const { createServer } = require("http");
const { existsSync, statSync, createReadStream } = require("fs");
const { access } = require("fs/promises");
const { extname, isAbsolute, join, normalize, relative, resolve } = require("path");
const { spawn, spawnSync } = require("child_process");

const rootDir = resolve(__dirname, "..");
const publicDir = join(rootDir, "public");
const frontendPort = Number(process.env.FRONTEND_PORT || 8888);
const backendPort = Number(process.env.BACKEND_PORT || 8000);
const mode = process.argv[2] || "all";
let shuttingDown = false;

const mimeTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

function findPython() {
  const candidates = process.platform === "win32"
    ? [["py", ["-3"]], ["python", []], ["python3", []]]
    : [["python3", []], ["python", []]];

  for (const [command, args] of candidates) {
    const result = spawnSync(command, [...args, "--version"], {
      encoding: "utf8",
      stdio: "pipe",
    });

    if (result.status === 0) {
      return { command, args };
    }
  }

  return null;
}

function startBackend({ full = false } = {}) {
  const python = findPython();
  if (!python) {
    console.error("[dev] Python non trovato. Installa Python 3 oppure aggiungilo al PATH.");
    process.exit(1);
  }

  const args = [
    ...python.args,
    "-m",
    "uvicorn",
    "main:app",
    "--host",
    "0.0.0.0",
    "--port",
    String(backendPort),
    "--reload",
    "--app-dir",
    "meteo-backend",
  ];

  const child = spawn(python.command, args, {
    cwd: rootDir,
    stdio: "inherit",
    env: {
      ...process.env,
      APP_ENV: process.env.APP_ENV || "development",
      FRONTEND_ORIGIN: process.env.FRONTEND_ORIGIN || `http://localhost:${frontendPort}`,
      DATABASE_URL: process.env.DATABASE_URL || "sqlite:///meteo-backend/meteo_ai.db",
      ENABLE_SCHEDULER: process.env.ENABLE_SCHEDULER || (full ? "true" : "false"),
      AUTO_LOAD_CITIES: process.env.AUTO_LOAD_CITIES || (full ? "true" : "false"),
    },
  });

  child.on("exit", (code, signal) => {
    if (shuttingDown) return;
    if (signal) return;
    if (code !== 0) {
      console.error(`[dev] Backend terminato con codice ${code}.`);
      process.exit(code || 1);
    }
  });

  return child;
}

async function resolveStaticPath(requestUrl) {
  const url = new URL(requestUrl, `http://localhost:${frontendPort}`);
  const decodedPath = decodeURIComponent(url.pathname);
  const requestedPath = decodedPath === "/" ? "/index.html" : decodedPath;
  const filePath = normalize(join(publicDir, requestedPath));
  const relativePath = relative(publicDir, filePath);

  if (relativePath.startsWith("..") || isAbsolute(relativePath)) {
    return null;
  }

  try {
    await access(filePath);
    const stats = statSync(filePath);
    if (stats.isDirectory()) {
      const indexPath = join(filePath, "index.html");
      return existsSync(indexPath) ? indexPath : null;
    }
    return filePath;
  } catch (_) {
    return null;
  }
}

function startFrontend() {
  const server = createServer(async (request, response) => {
    const filePath = await resolveStaticPath(request.url || "/");

    if (!filePath) {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Not found");
      return;
    }

    const contentType = mimeTypes[extname(filePath)] || "application/octet-stream";
    response.writeHead(200, {
      "Content-Type": contentType,
      "Cache-Control": "no-store",
    });
    createReadStream(filePath).pipe(response);
  });

  server.listen(frontendPort, () => {
    console.log(`[dev] Frontend: http://localhost:${frontendPort}`);
    if (mode === "all") {
      console.log(`[dev] Backend:  http://localhost:${backendPort}`);
    }
  });

  server.on("error", error => {
    if (error.code === "EADDRINUSE") {
      console.error(`[dev] Porta ${frontendPort} gia' in uso. Chiudi il server esistente o imposta FRONTEND_PORT.`);
      process.exit(1);
    }
    throw error;
  });

  return server;
}

const startsBackend = mode !== "--frontend-only";
const startsFrontend = mode !== "--backend-only" && mode !== "--backend-full";
const backend = startsBackend ? startBackend({ full: mode === "--backend-full" }) : null;
const frontend = startsFrontend ? startFrontend() : null;

function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  if (frontend) {
    frontend.close();
  }
  if (backend && !backend.killed) {
    backend.kill();
  }
  setTimeout(() => process.exit(0), 500).unref();
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
