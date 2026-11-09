/**
 * dsh-hoi4-modding — DeepSeek Harness 组合包入口（ESM，纯 Node 内置模块）。
 *
 * 这个入口做两件事：
 * 1. 把包内 skills/kiant-hoi4-* 的 15 个技能注册进 DSH 的 skill 注册表
 *    （用 registerProvider 按需读取 SKILL.md，不把全部正文塞进启动期内存）。
 * 2. 通过 DSH 自带的 @deepseek-ai/dsh-mcp-client 起一个 stdio MCP 服务器
 *    （python mcp-server/server.py），把 20 个 kiant_hoi4_* 工具注册为
 *    mcp__kiant_hoi4_modkit__<tool>。
 *
 * 没有 Python 3、或当前 DSH 版本没有 mcp-client 时，只记录警告，不阻断插件加载：
 * 技能仍然可用，工具缺席。
 */

import { existsSync } from 'node:fs';
import { readFile, readdir } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

/** 包根目录（带尾部分隔符的绝对路径）。 */
const PACKAGE_DIR = fileURLToPath(new URL('../', import.meta.url));
const SKILLS_DIR = join(PACKAGE_DIR, 'skills');
const SERVER_FILE = join(PACKAGE_DIR, 'mcp-server', 'server.py');

/** skill provider 名称，与 1.x 的单技能实现保持一致。 */
const PROVIDER_NAME = 'hoi4-modding';
/** @deepseek-ai/dsh-skill 的 BUNDLED_SKILL_RANK；硬编码以免把 DSH 内部包变成硬依赖。 */
const PROVIDER_RANK = 600;
/** MCP 服务器命名空间；工具名形如 mcp__kiant_hoi4_modkit__kiant_hoi4_validate_mod。 */
const SERVER_NAME = 'kiant_hoi4_modkit';
const SERVER_NAME_SAFE = /^[A-Za-z0-9_-]{1,32}$/;

const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/u;
const PREFIX = '[dsh-hoi4-modding] ';

function warn(ctx, message) {
  ctx?.logger?.warn?.(PREFIX + message);
}

function info(ctx, message) {
  ctx?.logger?.info?.(PREFIX + message);
}

function unquote(value) {
  const text = value.trim();
  if (text.length >= 2) {
    const first = text[0];
    const last = text[text.length - 1];
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      return text.slice(1, -1).replace(/\\"/g, '"');
    }
  }
  return text;
}

/** 只解析 frontmatter 里我们需要的单行 name/description，不引入 YAML 依赖。 */
function parseFrontmatter(raw) {
  const match = raw.match(FRONTMATTER);
  if (match === null) return { attributes: {}, content: raw.trimStart() };
  const attributes = {};
  for (const line of match[1].split(/\r?\n/u)) {
    const separator = line.indexOf(':');
    if (separator === -1) continue;
    const key = line.slice(0, separator).trim();
    if (key === '' || key.startsWith('#')) continue;
    attributes[key] = unquote(line.slice(separator + 1));
  }
  return { attributes, content: raw.slice(match[0].length).trimStart() };
}

function resourceBaseOf(directory) {
  return { kind: 'directory', path: directory.split('\\').join('/') };
}

/** 扫描包内 skills/ 下的技能目录，读取每个 SKILL.md 的 frontmatter 生成候选。 */
async function discoverSkills(ctx) {
  const candidates = [];
  let entries;
  try {
    entries = await readdir(SKILLS_DIR, { withFileTypes: true });
  } catch (error) {
    warn(ctx, 'skills directory is unavailable: ' + (error?.message ?? error));
    return candidates;
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const directory = join(SKILLS_DIR, entry.name);
    const locator = join(directory, 'SKILL.md');
    if (!existsSync(locator)) continue;
    let raw;
    try {
      raw = await readFile(locator, 'utf8');
    } catch (error) {
      warn(ctx, 'failed to read ' + entry.name + '/SKILL.md: ' + (error?.message ?? error));
      continue;
    }
    const attributes = parseFrontmatter(raw).attributes;
    const skillName = (attributes.name || entry.name).trim();
    const description = (attributes.description || '').trim();
    if (skillName === '' || description === '') {
      warn(ctx, 'skip skill ' + entry.name + ': frontmatter needs name and description');
      continue;
    }
    candidates.push({
      name: skillName,
      description,
      invocation: { modelInvocable: true, userInvocable: true },
      provider: PROVIDER_NAME,
      source: 'bundled',
      rank: PROVIDER_RANK,
      resourceBase: resourceBaseOf(directory),
      locator,
      path: locator,
    });
  }
  candidates.sort((left, right) => left.name.localeCompare(right.name));
  return candidates;
}

function createProvider(ctx, candidates) {
  const provider = {
    name: PROVIDER_NAME,
    async list() {
      return candidates;
    },
    async get(candidate) {
      const locator = candidate?.locator || candidate?.path;
      if (typeof locator !== 'string' || locator === '') throw new Error('skill candidate has no locator');
      const raw = await readFile(locator, 'utf8');
      const parsed = parseFrontmatter(raw);
      return {
        name: candidate.name,
        description: (parsed.attributes.description || candidate.description || '').trim(),
        content: parsed.content,
        path: locator,
        source: 'bundled',
        provider: PROVIDER_NAME,
        invocation: candidate.invocation,
        resourceBase: candidate.resourceBase,
      };
    },
  };
  ctx.skills.registerProvider(() => provider);
}

function findPython() {
  const candidates = process.platform === 'win32'
    ? ['python', 'python3', 'py']
    : ['python3', 'python'];
  for (const command of candidates) {
    const probe = spawnSync(command, ['-c', 'import sys; print(sys.version_info[0])'], {
      encoding: 'utf8',
      timeout: 5000,
      windowsHide: true,
    });
    if (probe.status === 0 && String(probe.stdout || '').trim() === '3') return command;
  }
  return undefined;
}

/**
 * 载入 DSH 内置的 mcp-client 插件。
 * 正常路径是裸导入（launcher 安装了 runtime resolution）；若宿主没装好解析，
 * 退回到 Electron 打包目录里的 app.asar 文件 URL。两条都失败才返回 undefined。
 */
async function loadMcpClient(ctx) {
  let firstError;
  try {
    return await import('@deepseek-ai/dsh-mcp-client');
  } catch (error) {
    firstError = error;
  }
  const roots = [];
  if (typeof process.resourcesPath === 'string' && process.resourcesPath !== '') roots.push(process.resourcesPath);
  roots.push(join(dirname(process.execPath), 'resources'));
  for (const root of roots) {
    const candidate = join(root, 'app.asar', 'dsh', 'node_modules', '@deepseek-ai', 'dsh-mcp-client', 'lib', 'index.js');
    if (!existsSync(candidate)) continue;
    try {
      return await import(pathToFileURL(candidate).href);
    } catch (error) {
      firstError = error;
    }
  }
  warn(ctx, 'this DSH build has no MCP client plugin; MCP tools are not attached (' + (firstError?.message ?? firstError) + ')');
  return undefined;
}

/** 借 DSH 自带的 mcp-client 插件挂载 python MCP 服务器；失败只警告。 */
async function mountMcp(ctx, config) {
  if (!existsSync(SERVER_FILE)) {
    warn(ctx, 'mcp-server/server.py is missing; MCP tools are not attached');
    return;
  }
  const python = typeof config?.python === 'string' && config.python !== '' ? config.python : findPython();
  if (python === undefined) {
    warn(ctx, 'Python 3 not found in PATH; MCP tools are not attached (install Python 3.9+ or pass config.python)');
    return;
  }
  const client = await loadMcpClient(ctx);
  if (client === undefined) return;
  const options = {
    transport: 'stdio',
    serverName: SERVER_NAME,
    command: python,
    args: [SERVER_FILE],
    cwd: PACKAGE_DIR,
    env: { PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
    toolCallTimeoutMs: 120000,
  };
  try {
    const resolved = typeof client.Config === 'function' ? client.Config(options) : options;
    if (!SERVER_NAME_SAFE.test(resolved.serverName)) throw new Error('invalid serverName');
    await client.apply(ctx, resolved);
    info(ctx, 'MCP server attached: ' + python + ' mcp-server/server.py (namespace ' + SERVER_NAME + ')');
  } catch (error) {
    warn(ctx, 'MCP server failed to attach: ' + (error?.message ?? error));
  }
}

export const name = 'hoi4-modding-skill';
export const inject = ['skills', 'tools'];

/**
 * @param {import('@deepseek-ai/cordis').Context} ctx
 * @param {{ mcp?: boolean, python?: string }} [config]
 */
export async function apply(ctx, config = {}) {
  const skills = ctx?.skills;
  if (skills === undefined || (typeof skills.registerProvider !== 'function' && typeof skills.register !== 'function')) {
    warn(ctx, 'skills registry is unavailable; skills are not registered');
  } else {
    const candidates = await discoverSkills(ctx);
    if (candidates.length === 0) {
      warn(ctx, 'no skills found next to the bundle entry');
    } else if (typeof skills.registerProvider === 'function') {
      try {
        createProvider(ctx, candidates);
        info(ctx, candidates.length + ' skills registered (provider ' + PROVIDER_NAME + ')');
      } catch (error) {
        warn(ctx, 'skill provider registration failed: ' + (error?.message ?? error));
      }
    } else {
      for (const candidate of candidates) {
        try {
          const raw = await readFile(candidate.locator, 'utf8');
          const parsed = parseFrontmatter(raw);
          skills.register({
            name: candidate.name,
            description: (parsed.attributes.description || candidate.description || '').trim(),
            content: parsed.content,
            path: candidate.locator,
            source: 'bundled',
            provider: PROVIDER_NAME,
            resourceBase: candidate.resourceBase,
          });
        } catch (error) {
          warn(ctx, 'skill ' + candidate.name + ' registration failed: ' + (error?.message ?? error));
        }
      }
      info(ctx, candidates.length + ' skills registered via ctx.skills.register');
    }
  }
  if (config?.mcp !== false) await mountMcp(ctx, config);
}

export default { name, inject, apply };
