declare module 'transformers' {
  export function pipeline(task: string, model: string, options?: { device?: string }): Promise<any>;
}

declare module 'torch' {
  export const cuda: { is_available: () => boolean };
}

declare module 'soundfile' {
  export function read(path: string, options?: { dtype?: string }): [any, number];
}

declare module 'scipy.signal' {
  export function resample(x: Float32Array, num: number): Float32Array;
}

declare module 'torchaudio' {
  export const functional: {
    resample: (waveform: any, orig_sr: number, new_sr: number) => any;
  };
  export function load(path: string): Promise<[any, number]>;
}