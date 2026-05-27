import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '🎙️ MP4 转文字',
  description: '视频转文字工具 - Whisper + MiniMax',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh">
      <body>{children}</body>
    </html>
  );
}