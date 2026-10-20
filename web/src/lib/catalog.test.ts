import { describe, expect, it } from 'vitest';
import { mcpHint, PROTOCOLS, TOOL_LABELS, toolCode } from './catalog';

describe('toolCode', () => {
  it('gives the protocol code of a tool', () => {
    expect(toolCode('get_weather')).toBe('WX-01');
    expect(toolCode('manage_screens')).toBe('JAN-13');
    expect(toolCode('confirm_calendar_change')).toBe('AGD-27');
    expect(toolCode('mcp')).toBe('MCP-32');
  });

  it('falls back to a generic code for unknown tools', () => {
    expect(toolCode('teleport')).toBe('PRT');
  });

  it('agrees with the Protocolos panel', () => {
    for (const protocol of PROTOCOLS) expect(toolCode(protocol.id)).toBe(protocol.code);
  });

  it('knows every tool the HUD has a label for', () => {
    expect(Object.keys(TOOL_LABELS).filter((name) => toolCode(name) === 'PRT')).toEqual([]);
  });
});

describe('mcpHint', () => {
  it('lists each MCP server with its tools, or why it is out', () => {
    expect(mcpHint(null)).toBeNull();
    expect(
      mcpHint({
        servers: [
          { name: 'github', label: 'GitHub', tools: ['list_issues', 'issue_read'], problems: [] },
          { name: 'notion', label: 'Notion', tools: [], problems: ['falta NOTION_TOKEN no .env'] },
        ],
        error: null,
      }),
    ).toBe('GitHub: list_issues, issue_read · Notion: falta NOTION_TOKEN no .env');
    expect(mcpHint({ servers: [], error: null })).toBe('Nenhum servidor no mcp.json');
    expect(mcpHint({ servers: [], error: 'O mcp.json precisa ser um objeto' })).toBe('O mcp.json precisa ser um objeto');
  });
});
