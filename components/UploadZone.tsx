import { useState } from 'react';

interface UploadZoneProps {
  onFileSelected: (file: File) => void;
  disabled: boolean;
}

export default function UploadZone({ onFileSelected, disabled }: UploadZoneProps) {
  const [dragging, setDragging] = useState(false);

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const file = e.dataTransfer.files[0];
        if (file) onFileSelected(file);
      }}
      onClick={() => {
        if (disabled) return;
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = 'video/*,audio/*,.mp4,.mov,.avi,.mkv,.wav,.mp3';
        input.onchange = (e) => {
          const file = (e.target as HTMLInputElement).files?.[0];
          if (file) onFileSelected(file);
        };
        input.click();
      }}
      style={{
        border: `2px dashed ${dragging ? '#1d9bf0' : '#2f3336'}`,
        borderRadius: '16px',
        padding: '48px',
        textAlign: 'center',
        cursor: disabled ? 'not-allowed' : 'pointer',
        background: dragging ? 'rgba(29,155,240,0.05)' : 'transparent',
        transition: 'all 0.2s ease',
      }}
    >
      <div style={{ fontSize: '48px', marginBottom: '16px' }}>📁</div>
      <div style={{ fontSize: '16px', color: '#e7e9ea', marginBottom: '8px' }}>
        点击选择 MP4 文件，或拖拽到此处
      </div>
      <div style={{ fontSize: '13px', color: '#71767b' }}>
        支持 MP4 / MOV / AVI / MKV / WAV / MP3
      </div>
    </div>
  );
}