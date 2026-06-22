import { motion } from 'framer-motion';

export default function GlassPanel({
  children,
  className = '',
  style = {},
  animate = true,
  delay = 0,
  ...rest
}) {
  const Wrapper = animate ? motion.div : 'div';
  const motionProps = animate
    ? {
        initial: { opacity: 0, y: 18 },
        animate: { opacity: 1, y: 0 },
        transition: { duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] },
      }
    : {};

  return (
    <Wrapper
      className={`glass-panel ${className}`}
      style={{
        background: 'rgba(12, 18, 32, 0.65)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid rgba(0, 229, 255, 0.08)',
        borderRadius: '16px',
        padding: '24px',
        ...style,
      }}
      {...motionProps}
      {...rest}
    >
      {children}
    </Wrapper>
  );
}
