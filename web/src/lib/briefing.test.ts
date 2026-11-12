import { describe, expect, it } from 'vitest';
import { greeting, suggestions } from './briefing';

const at = (hour: number, day = 12) => new Date(2026, 10, day, hour, 30);

describe('saudação', () => {
  it('muda com a hora do dia', () => {
    expect(greeting(at(3))).toBe('Boa madrugada');
    expect(greeting(at(5))).toBe('Bom dia');
    expect(greeting(at(11))).toBe('Bom dia');
    expect(greeting(at(12))).toBe('Boa tarde');
    expect(greeting(at(18))).toBe('Boa noite');
    expect(greeting(at(23))).toBe('Boa noite');
  });
});

describe('sugestões do briefing', () => {
  it('só usa protocolos ligados e nunca o de encerrar', () => {
    const found = suggestions(['get_weather', 'end_session', 'set_volume'], at(9));
    expect(found.map((item) => item.id)).toEqual(['get_weather', 'set_volume']);
    expect(found[0].phrase).toBe('Como está o tempo em Lisboa?');
    expect(suggestions([], at(9))).toEqual([]);
  });

  it('gira com o dia e fica igual ao longo do mesmo dia', () => {
    const morning = suggestions(null, at(8)).map((item) => item.id);
    const night = suggestions(null, at(22)).map((item) => item.id);
    const tomorrow = suggestions(null, at(8, 13)).map((item) => item.id);
    expect(morning).toHaveLength(3);
    expect(night).toEqual(morning);
    expect(tomorrow).not.toEqual(morning);
    expect(new Set(morning).size).toBe(3);
  });

  it('não oferece frases compridas demais para um botão', () => {
    for (const item of suggestions(null, at(8), 50)) expect(item.phrase.length).toBeLessThanOrEqual(44);
  });
});
