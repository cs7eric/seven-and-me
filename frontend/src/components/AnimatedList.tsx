import React, { useEffect, useRef, useState, useCallback } from 'react';
import type { ReactNode, MouseEventHandler, UIEvent } from 'react';
import { motion, useInView } from 'motion/react';

interface AnimatedItemProps {
  children: ReactNode;
  delay?: number;
  index: number;
  selected?: boolean;
  onMouseEnter?: MouseEventHandler<HTMLDivElement>;
  onClick?: MouseEventHandler<HTMLDivElement>;
}

const AnimatedItem: React.FC<AnimatedItemProps> = ({ children, delay = 0, index, selected, onMouseEnter, onClick }) => {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { amount: 0.2, once: false });
  return (
    <motion.div
      ref={ref}
      data-index={index}
      data-selected={selected ? 'true' : 'false'}
      onMouseEnter={onMouseEnter}
      onClick={onClick}
      initial={{ scale: 0.92, opacity: 0, y: 6 }}
      animate={inView ? { scale: 1, opacity: 1, y: 0 } : { scale: 0.92, opacity: 0, y: 6 }}
      transition={{ duration: 0.22, delay, ease: 'easeOut' }}
      className="mb-2 cursor-pointer"
    >
      {children}
    </motion.div>
  );
};

export interface AnimatedListProps<T = unknown> {
  items?: T[]
  onItemSelect?: (item: T, index: number) => void
  showGradients?: boolean
  enableArrowNavigation?: boolean
  className?: string
  itemClassName?: string
  displayScrollbar?: boolean
  initialSelectedIndex?: number
  selectedIndex?: number
  renderItem?: (item: T, index: number) => ReactNode
  emptyMessage?: ReactNode
  maxHeight?: string
}

const AnimatedList = <T,>({
  items = [] as T[],
  onItemSelect,
  showGradients = true,
  enableArrowNavigation = true,
  className = '',
  itemClassName = '',
  displayScrollbar = true,
  initialSelectedIndex = -1,
  selectedIndex: controlledSelectedIndex,
  renderItem,
  emptyMessage,
  maxHeight = 'max-h-[480px]',
}: AnimatedListProps<T>) => {
  const listRef = useRef<HTMLDivElement>(null);
  const isControlled = controlledSelectedIndex !== undefined && controlledSelectedIndex !== null;
  const [internalSelectedIndex, setInternalSelectedIndex] = useState<number>(initialSelectedIndex);
  const selectedIndex = isControlled ? (controlledSelectedIndex as number) : internalSelectedIndex;
  const [keyboardNav, setKeyboardNav] = useState<boolean>(false);
  const [topGradientOpacity, setTopGradientOpacity] = useState<number>(0);
  const [bottomGradientOpacity, setBottomGradientOpacity] = useState<number>(1);

  const handleItemMouseEnter = useCallback((index: number) => {
    if (!isControlled) {
      setInternalSelectedIndex(index);
    }
  }, [isControlled]);

  const handleItemClick = useCallback(
    (item: T, index: number) => {
      if (!isControlled) {
        setInternalSelectedIndex(index);
      }
      if (onItemSelect) {
        onItemSelect(item, index);
      }
    },
    [onItemSelect, isControlled]
  );

  const handleScroll = (e: UIEvent<HTMLDivElement>) => {
    const target = e.target as HTMLDivElement;
    const { scrollTop, scrollHeight, clientHeight } = target;
    setTopGradientOpacity(Math.min(scrollTop / 50, 1));
    const bottomDistance = scrollHeight - (scrollTop + clientHeight);
    setBottomGradientOpacity(scrollHeight <= clientHeight ? 0 : Math.min(bottomDistance / 50, 1));
  };

  useEffect(() => {
    if (!enableArrowNavigation || isControlled) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (items.length === 0) return;
      if (e.key === 'ArrowDown' || (e.key === 'Tab' && !e.shiftKey)) {
        e.preventDefault();
        setKeyboardNav(true);
        setInternalSelectedIndex((prev) => Math.min(prev + 1, items.length - 1));
      } else if (e.key === 'ArrowUp' || (e.key === 'Tab' && e.shiftKey)) {
        e.preventDefault();
        setKeyboardNav(true);
        setInternalSelectedIndex((prev) => Math.max(prev - 1, 0));
      } else if (e.key === 'Enter') {
        if (selectedIndex >= 0 && selectedIndex < items.length) {
          e.preventDefault();
          if (onItemSelect) {
            onItemSelect(items[selectedIndex], selectedIndex);
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [items, selectedIndex, onItemSelect, enableArrowNavigation, isControlled]);

  useEffect(() => {
    if (!keyboardNav || selectedIndex < 0 || !listRef.current) return;
    const container = listRef.current;
    const selectedItem = container.querySelector(`[data-index="${selectedIndex}"]`) as HTMLElement | null;
    if (selectedItem) {
      const extraMargin = 50;
      const containerScrollTop = container.scrollTop;
      const containerHeight = container.clientHeight;
      const itemTop = selectedItem.offsetTop;
      const itemBottom = itemTop + selectedItem.offsetHeight;
      if (itemTop < containerScrollTop + extraMargin) {
        container.scrollTo({ top: itemTop - extraMargin, behavior: 'smooth' });
      } else if (itemBottom > containerScrollTop + containerHeight - extraMargin) {
        container.scrollTo({
          top: itemBottom - containerHeight + extraMargin,
          behavior: 'smooth',
        });
      }
    }
    setKeyboardNav(false);
  }, [selectedIndex, keyboardNav]);

  const hasItems = items.length > 0;

  return (
    <div className={`relative w-full ${className}`}>
      <div
        ref={listRef}
        className={`${maxHeight} overflow-y-auto p-2 ${
          displayScrollbar
            ? '[&::-webkit-scrollbar]:w-[6px] [&::-webkit-scrollbar-thumb]:bg-slate-300 [&::-webkit-scrollbar-thumb]:rounded-full'
            : 'scrollbar-hide'
        }`}
        style={{
          scrollbarWidth: displayScrollbar ? 'thin' : 'none',
          scrollbarColor: '#cbd5e1 transparent',
        }}
        onScroll={handleScroll}
      >
        {!hasItems ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-center text-sm text-slate-500">
            {emptyMessage ?? '暂无数据。'}
          </div>
        ) : (
          items.map((item, index) => (
            <AnimatedItem
              key={index}
              delay={0.04}
              index={index}
              selected={selectedIndex === index}
              onMouseEnter={() => handleItemMouseEnter(index)}
              onClick={() => handleItemClick(item, index)}
            >
              <div className={`${itemClassName}`}>
                {renderItem ? renderItem(item, index) : <p className="m-0 text-sm text-slate-700">{typeof item === 'string' ? item : ''}</p>}
              </div>
            </AnimatedItem>
          ))
        )}
      </div>
      {showGradients && hasItems ? (
        <>
          <div
            className="pointer-events-none absolute top-0 left-0 right-0 h-[40px] bg-gradient-to-b from-white to-transparent transition-opacity duration-300"
            style={{ opacity: topGradientOpacity }}
          />
          <div
            className="pointer-events-none absolute bottom-0 left-0 right-0 h-[60px] bg-gradient-to-t from-white to-transparent transition-opacity duration-300"
            style={{ opacity: bottomGradientOpacity }}
          />
        </>
      ) : null}
    </div>
  );
};

export default AnimatedList;
