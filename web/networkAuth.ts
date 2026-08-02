import { readFileSync } from "node:fs";
import { isIP } from "node:net";

const MAX_SETTINGS_BYTES = 128 * 1024;
const MAX_TRUSTED_NETWORKS = 32;

type ParsedAddress = {
  bits: 32 | 128;
  bytes: number[];
};

type NetworkAuthSettings = {
  enabled: boolean;
  trustProxyHeaders: boolean;
  trustedNetworks: string[];
};

const DISABLED_SETTINGS: NetworkAuthSettings = {
  enabled: false,
  trustProxyHeaders: false,
  trustedNetworks: [],
};

function runtimeSettingsPath(): string {
  return process.env.RUNTIME_SETTINGS_FILE?.trim() || "/config/runtime_settings.json";
}

function loadNetworkAuthSettings(): NetworkAuthSettings {
  try {
    const raw = readFileSync(/* turbopackIgnore: true */ runtimeSettingsPath(), "utf8");
    if (Buffer.byteLength(raw, "utf8") > MAX_SETTINGS_BYTES) return DISABLED_SETTINGS;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return DISABLED_SETTINGS;
    const settings = parsed as Record<string, unknown>;
    const networks = settings.web_auth_trusted_networks;
    if (!Array.isArray(networks) || networks.length > MAX_TRUSTED_NETWORKS) return DISABLED_SETTINGS;
    return {
      enabled: settings.web_auth_bypass_enabled === true,
      trustProxyHeaders: settings.web_auth_trust_proxy_headers === true,
      trustedNetworks: networks.filter((network): network is string => typeof network === "string"),
    };
  } catch {
    return DISABLED_SETTINGS;
  }
}

function parseIpv4(address: string): ParsedAddress | null {
  const octets = address.split(".");
  if (octets.length !== 4) return null;
  const bytes: number[] = [];
  for (const octet of octets) {
    const number = Number(octet);
    if (!Number.isInteger(number) || number < 0 || number > 255) return null;
    bytes.push(number);
  }
  return { bits: 32, bytes };
}

function parseIpv6(address: string): ParsedAddress | null {
  let normalized = address.toLowerCase();
  const ipv4Start = normalized.lastIndexOf(":") + 1;
  const ipv4Suffix = normalized.slice(ipv4Start);
  if (ipv4Suffix.includes(".")) {
    const ipv4 = parseIpv4(ipv4Suffix);
    if (!ipv4) return null;
    const high = ((ipv4.bytes[0] << 8) | ipv4.bytes[1]).toString(16);
    const low = ((ipv4.bytes[2] << 8) | ipv4.bytes[3]).toString(16);
    normalized = `${normalized.slice(0, ipv4Start)}${high}:${low}`;
  }

  const halves = normalized.split("::");
  if (halves.length > 2) return null;
  const left = halves[0] ? halves[0].split(":") : [];
  const right = halves.length === 2 && halves[1] ? halves[1].split(":") : [];
  const missing = 8 - left.length - right.length;
  if ((halves.length === 1 && missing !== 0) || (halves.length === 2 && missing < 1)) return null;
  const groups = [...left, ...Array<string>(missing).fill("0"), ...right];
  if (groups.length !== 8 || groups.some((group) => !/^[0-9a-f]{1,4}$/.test(group))) return null;

  const bytes = groups.flatMap((group) => {
    const value = Number.parseInt(group, 16);
    return [value >> 8, value & 0xff];
  });
  return { bits: 128, bytes };
}

function cleanIp(value: string): string {
  let cleaned = value.trim().replace(/^"|"$/g, "");
  if (cleaned.startsWith("[") && cleaned.includes("]")) {
    cleaned = cleaned.slice(1, cleaned.indexOf("]"));
  } else if (isIP(cleaned) === 0) {
    const ipv4WithPort = cleaned.match(/^(\d{1,3}(?:\.\d{1,3}){3}):\d+$/);
    if (ipv4WithPort) cleaned = ipv4WithPort[1];
  }
  return cleaned;
}

function parseAddress(raw: string): ParsedAddress | null {
  const address = cleanIp(raw);
  const version = isIP(address);
  if (version === 4) return parseIpv4(address);
  if (version !== 6) return null;

  const mappedMatch = address.match(/^::ffff:(\d{1,3}(?:\.\d{1,3}){3})$/i);
  if (mappedMatch) return parseIpv4(mappedMatch[1]);
  return parseIpv6(address);
}

function parseNetwork(raw: string): { address: ParsedAddress; prefix: number } | null {
  const parts = raw.trim().split("/");
  if (parts.length > 2) return null;
  const address = parseAddress(parts[0]);
  if (!address) return null;
  const prefix = parts.length === 1 ? address.bits : Number(parts[1]);
  if (!Number.isInteger(prefix) || prefix < 0 || prefix > address.bits) return null;
  return { address, prefix };
}

function addressInNetwork(address: ParsedAddress, network: string): boolean {
  const parsedNetwork = parseNetwork(network);
  if (!parsedNetwork || parsedNetwork.address.bits !== address.bits) return false;
  const fullBytes = Math.floor(parsedNetwork.prefix / 8);
  for (let index = 0; index < fullBytes; index += 1) {
    if (address.bytes[index] !== parsedNetwork.address.bytes[index]) return false;
  }
  const remainingBits = parsedNetwork.prefix % 8;
  if (remainingBits === 0) return true;
  const mask = (0xff << (8 - remainingBits)) & 0xff;
  return (address.bytes[fullBytes] & mask) === (parsedNetwork.address.bytes[fullBytes] & mask);
}

function forwardedClientIp(request: Request): string | null {
  const candidates = [
    request.headers.get("cf-connecting-ip"),
    request.headers.get("x-forwarded-for")?.split(",", 1)[0],
    request.headers.get("x-real-ip"),
  ];
  for (const candidate of candidates) {
    if (candidate && parseAddress(candidate)) return cleanIp(candidate);
  }
  return null;
}

export function trustedProxyClientIp(request: Request): string | null {
  const settings = loadNetworkAuthSettings();
  const environmentTrust = process.env.WEB_TRUST_PROXY?.trim().toLowerCase() === "true";
  if (!settings.trustProxyHeaders && !environmentTrust) return null;
  return forwardedClientIp(request);
}

export function requestBypassesWebAuth(request: Request): boolean {
  const settings = loadNetworkAuthSettings();
  if (!settings.enabled || !settings.trustProxyHeaders || settings.trustedNetworks.length === 0) return false;
  const clientIp = forwardedClientIp(request);
  const address = clientIp ? parseAddress(clientIp) : null;
  return address !== null && settings.trustedNetworks.some((network) => addressInNetwork(address, network));
}
