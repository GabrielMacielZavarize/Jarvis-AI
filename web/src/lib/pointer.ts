import type { PointerData } from './types';

/** How many annotated prints (blob URLs) the browser keeps for the MOU-20 panel. */
const MAX_IMAGES = 6;

/**
 * Prints of the mouse/keyboard actions arrive on the `jarvis.pointer` byte stream, apart from
 * the card JSON, and either one can land first. Both carry the same `action_id`.
 */
export class PointerImages {
  private readonly urls = new Map<string, string>();

  constructor(private readonly revoke: (url: string) => void = (url) => URL.revokeObjectURL(url)) {}

  remember(actionId: string, url: string): void {
    const previous = this.urls.get(actionId);
    if (previous && previous !== url) this.revoke(previous);
    this.urls.delete(actionId);
    this.urls.set(actionId, url);
    while (this.urls.size > MAX_IMAGES) {
      const [oldestId, oldestUrl] = this.urls.entries().next().value as [string, string];
      this.urls.delete(oldestId);
      this.revoke(oldestUrl);
    }
  }

  get(actionId: string): string | undefined {
    return this.urls.get(actionId);
  }
}

/** The card data with its print, when the print for that action already arrived. */
export function withPointerImage(data: PointerData, images: PointerImages): PointerData {
  const image = images.get(data.action_id);
  return image ? { ...data, image } : data;
}
