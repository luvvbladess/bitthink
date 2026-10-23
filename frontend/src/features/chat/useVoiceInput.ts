import { useEffect, useRef, useState } from 'react';
import { apiFormData } from '@/api/client';

type VoiceState = 'idle' | 'starting' | 'recording' | 'transcribing' | 'error';

export function useVoiceInput(scope: string | null | undefined, onText: (text: string) => void, enabled = true) {
  const [voiceState, setVoiceState] = useState<VoiceState>('idle');
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const errorTimer = useRef<ReturnType<typeof setTimeout>>();
  const generation = useRef(0);
  const onTextRef = useRef(onText);
  onTextRef.current = onText;

  useEffect(() => {
    setVoiceState('idle');
    return () => {
      generation.current++;
      clearTimeout(errorTimer.current);
      requestRef.current?.abort();
      const recorder = recorderRef.current;
      if (recorder) {
        recorder.onstop = null;
        if (recorder.state !== 'inactive') recorder.stop();
      }
      streamRef.current?.getTracks().forEach(track => track.stop());
      streamRef.current = null;
      recorderRef.current = null;
    };
  }, [scope, enabled]);

  async function start() {
    if (!enabled) return;
    const attempt = ++generation.current;
    clearTimeout(errorTimer.current);
    setVoiceState('starting');
    const fail = () => {
      if (generation.current !== attempt) return;
      setVoiceState('error');
      errorTimer.current = setTimeout(() => setVoiceState('idle'), 3000);
    };
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (generation.current !== attempt) { stream.getTracks().forEach(track => track.stop()); return; }
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      const chunks: Blob[] = [];
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recorder.onerror = () => { stream.getTracks().forEach(track => track.stop()); fail(); };
      recorder.onstop = async () => {
        stream.getTracks().forEach(track => track.stop());
        if (generation.current !== attempt) return;
        setVoiceState('transcribing');
        const controller = new AbortController();
        requestRef.current = controller;
        try {
          const mimeType = recorder.mimeType || 'audio/webm';
          const extension = (mimeType.split('/')[1] || 'webm').split(';')[0];
          const form = new FormData();
          form.append('file', new Blob(chunks, { type: mimeType }), `recording.${extension}`);
          const response = await apiFormData('/media/audio/transcribe', form, { signal: controller.signal, timeoutMs: 60_000 });
          if (!response.ok) throw new Error('transcription failed');
          const data = await response.json();
          if (generation.current !== attempt) return;
          const text = typeof data.text === 'string' ? data.text.trim() : '';
          if (!text || text.startsWith('❌')) throw new Error('empty transcription');
          onTextRef.current(text);
          setVoiceState('idle');
        } catch { fail(); }
        finally { if (requestRef.current === controller) requestRef.current = null; }
      };
      recorder.start();
      setVoiceState('recording');
    } catch {
      streamRef.current?.getTracks().forEach(track => track.stop());
      fail();
    }
  }

  return { voiceState, handleMicClick: () => {
    if (voiceState === 'idle') void start();
    else if (voiceState === 'recording') recorderRef.current?.stop();
  } };
}
