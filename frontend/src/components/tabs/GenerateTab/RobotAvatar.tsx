export default function RobotAvatar() {
  return (
    <div className="relative flex h-[170px] w-[210px] items-center justify-center">
      {/* 背景光晕 */}
      <div className="absolute h-[140px] w-[140px] animate-soft-pulse rounded-full bg-gradient-to-b from-[#d9e9ff] to-[#edf5ff] opacity-80 blur-xl" />
      {/* 机器人本体：整体漂浮，眼睛定时眨动 */}
      <svg
        viewBox="0 0 120 120"
        className="relative h-[120px] w-[120px] animate-float drop-shadow-[0_10px_20px_rgba(59,110,220,0.18)]"
      >
        <defs>
          <linearGradient id="robot-body" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="100%" stopColor="#e8f1ff" />
          </linearGradient>
          <linearGradient id="robot-visor" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#274b8f" />
            <stop offset="100%" stopColor="#16294f" />
          </linearGradient>
        </defs>
        {/* 天线 */}
        <line x1="60" y1="14" x2="60" y2="26" stroke="#9ec1f7" strokeWidth="3" strokeLinecap="round" />
        <circle cx="60" cy="11" r="4.5" fill="#3e8bff" className="animate-twinkle" />
        {/* 耳朵 */}
        <rect x="10" y="52" width="9" height="22" rx="4.5" fill="#bfd9ff" />
        <rect x="101" y="52" width="9" height="22" rx="4.5" fill="#bfd9ff" />
        {/* 头 */}
        <rect x="17" y="26" width="86" height="64" rx="22" fill="url(#robot-body)" stroke="#dce7f8" strokeWidth="1.5" />
        {/* 面罩 */}
        <rect x="27" y="38" width="66" height="40" rx="15" fill="url(#robot-visor)" />
        {/* 眼睛（眨眼动画） */}
        <circle
          cx="46"
          cy="58"
          r="6.5"
          fill="#55d9ff"
          style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
          className="animate-blink"
        />
        <circle
          cx="74"
          cy="58"
          r="6.5"
          fill="#55d9ff"
          style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
          className="animate-blink"
        />
        <circle cx="48" cy="56" r="2" fill="#c8f4ff" />
        <circle cx="76" cy="56" r="2" fill="#c8f4ff" />
        {/* 腮红 */}
        <circle cx="33" cy="70" r="3" fill="#7fb3ff" opacity="0.45" />
        <circle cx="87" cy="70" r="3" fill="#7fb3ff" opacity="0.45" />
        {/* 身体 */}
        <rect x="40" y="94" width="40" height="16" rx="8" fill="url(#robot-body)" stroke="#dce7f8" strokeWidth="1.5" />
        <circle cx="60" cy="102" r="3.5" fill="#3e8bff" opacity="0.85" />
      </svg>
      {/* 对话气泡：三点跳动 */}
      <div className="absolute right-2 top-1 flex animate-float-delay items-center gap-1 rounded-full border border-line bg-white px-2.5 py-1.5 shadow-md">
        <span className="h-1.5 w-1.5 animate-dot rounded-full bg-primary/80" />
        <span className="h-1.5 w-1.5 animate-dot rounded-full bg-primary/80 [animation-delay:0.15s]" />
        <span className="h-1.5 w-1.5 animate-dot rounded-full bg-primary/80 [animation-delay:0.3s]" />
      </div>
      {/* 点缀星星 */}
      <span className="absolute bottom-6 left-3 animate-twinkle text-[#bbd4fa]">✦</span>
      <span className="absolute bottom-2 right-8 animate-twinkle text-sm text-[#cbdefb] [animation-delay:0.8s]">✦</span>
    </div>
  )
}
