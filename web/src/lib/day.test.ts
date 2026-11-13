import { describe, expect, it } from 'vitest';
import { formatChange, formatNumber, formatQuote, tasksSummary } from './day';

describe('formatação do dia a dia', () => {
  it('escreve números à brasileira', () => {
    expect(formatNumber(1234.5)).toBe('1.234,50');
    expect(formatNumber(0.5, 0)).toMatch(/^[01]$/);
  });

  it('usa as casas que fazem sentido para cada moeda', () => {
    expect(formatQuote(5.4321)).toBe('R$ 5,43');
    expect(formatQuote(612345.67)).toBe('R$ 612.346');
    expect(formatQuote(0.0312)).toBe('R$ 0,0312');
  });

  it('marca alta, queda e estável', () => {
    expect(formatChange(1.234)).toEqual({ text: '+1,23%', tone: 'up' });
    expect(formatChange(-0.5)).toEqual({ text: '-0,50%', tone: 'down' });
    expect(formatChange(0)).toEqual({ text: '0,00%', tone: 'flat' });
    expect(formatChange(null)).toEqual({ text: '', tone: 'flat' });
  });

  it('resume as tarefas numa linha', () => {
    expect(tasksSummary({ open: 3, overdue: 1, due_today: 2, done_today: 0 })).toBe('3 abertas · 1 atrasada · 2 para hoje');
    expect(tasksSummary({ open: 1, overdue: 0, due_today: 0, done_today: 4 })).toBe('1 aberta');
    expect(tasksSummary({ open: 0, overdue: 0, due_today: 0, done_today: 2 })).toBe('Tudo feito · 2 hoje');
    expect(tasksSummary({ open: 0, overdue: 0, due_today: 0, done_today: 0 })).toBe('Nada pendente');
  });
});
