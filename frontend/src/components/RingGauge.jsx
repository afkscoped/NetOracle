import React from 'react';

export default function RingGauge({
  value = 0,
  min = 0,
  max = 1,
  size = 120,
  strokeWidth = 10,
  title = '',
  colorMap = null,
  formatValue = (val) => `${Math.round(val * 100)}%`,
}) {
  const percentage = Math.min(Math.max((value - min) / (max - min), 0), 1);
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const strokeDashoffset = circumference - percentage * circumference;

  // Default color-coding from green (low) to red (high)
  let strokeColor = '#10b981'; // Green
  if (colorMap) {
    strokeColor = colorMap(value);
  } else {
    if (value > 0.7) {
      strokeColor = '#ef4444'; // Red
    } else if (value > 0.4) {
      strokeColor = '#f59e0b'; // Amber
    }
  }

  return (
    <div className="flex flex-col items-center justify-center relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="transform -rotate-90">
        {/* Track circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="transparent"
          stroke="rgba(255, 255, 255, 0.05)"
          strokeWidth={strokeWidth}
        />
        {/* Value circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="transparent"
          stroke={strokeColor}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset 0.8s cubic-bezier(0.4, 0, 0.2, 1)' }}
        />
      </svg>
      {/* Centered Text */}
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        <span className="text-xl font-bold tracking-wider" style={{ color: '#f3f4f6', fontFamily: 'Orbitron, sans-serif' }}>
          {formatValue(value)}
        </span>
        {title && <span className="text-[10px] text-gray-400 mt-1 uppercase tracking-wider">{title}</span>}
      </div>
    </div>
  );
}
