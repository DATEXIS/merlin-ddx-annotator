import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

const GAP = 8
const VIEWPORT_MARGIN = 16

interface Position {
  left: number
  top: number
  width: number
  maxHeight: number
  ready: boolean
}

interface Props {
  ariaLabel: string
  children: ReactNode
  content: ReactNode
  className?: string
  wrapperClassName?: string
  maxWidth?: number
}

export function HoverCard({
  ariaLabel,
  children,
  content,
  className = '',
  wrapperClassName = '',
  maxWidth = 640,
}: Props) {
  const id = useId()
  const triggerRef = useRef<HTMLSpanElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const closeTimer = useRef<number | null>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [position, setPosition] = useState<Position>({
    left: VIEWPORT_MARGIN,
    top: VIEWPORT_MARGIN,
    width: maxWidth,
    maxHeight: 0,
    ready: false,
  })

  const open = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
    setIsOpen(true)
  }, [])

  const close = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current)
    }
    closeTimer.current = window.setTimeout(() => {
      setIsOpen(false)
      closeTimer.current = null
    }, 100)
  }, [])

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current
    const popover = popoverRef.current
    if (!trigger || !popover) {
      return
    }

    const triggerRect = trigger.getBoundingClientRect()
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight
    const width = Math.max(1, Math.min(maxWidth, viewportWidth - VIEWPORT_MARGIN * 2))
    const availableBelow = viewportHeight - triggerRect.bottom - GAP - VIEWPORT_MARGIN
    const availableAbove = triggerRect.top - GAP - VIEWPORT_MARGIN
    const naturalHeight = popover.scrollHeight
    const placeBelow = availableBelow >= Math.min(naturalHeight, viewportHeight * 0.75)
      || availableBelow >= availableAbove
    const availableHeight = Math.max(120, placeBelow ? availableBelow : availableAbove)
    const maxHeight = Math.min(
      naturalHeight,
      viewportHeight - VIEWPORT_MARGIN * 2,
      availableHeight,
    )
    const left = Math.min(
      Math.max(VIEWPORT_MARGIN, triggerRect.left),
      viewportWidth - VIEWPORT_MARGIN - width,
    )
    const top = placeBelow
      ? triggerRect.bottom + GAP
      : Math.max(VIEWPORT_MARGIN, triggerRect.top - GAP - maxHeight)

    setPosition({ left, top, width, maxHeight, ready: true })
  }, [maxWidth])

  useLayoutEffect(() => {
    if (isOpen) {
      updatePosition()
    }
  }, [isOpen, updatePosition])

  useEffect(() => {
    if (!isOpen) {
      return
    }
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [isOpen, updatePosition])

  useEffect(() => () => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current)
    }
  }, [])

  return (
    <span className={`inline-flex min-w-0 ${wrapperClassName}`}>
      <span
        ref={triggerRef}
        tabIndex={0}
        aria-label={ariaLabel}
        aria-describedby={isOpen ? id : undefined}
        onMouseEnter={open}
        onMouseLeave={close}
        onFocus={open}
        onBlur={close}
        onKeyDown={event => {
          if (event.key === 'Escape') {
            setIsOpen(false)
            event.currentTarget.blur()
          }
        }}
        className={className}
      >
        {children}
      </span>
      {isOpen && createPortal(
        <div
          ref={popoverRef}
          id={id}
          role="tooltip"
          onMouseEnter={open}
          onMouseLeave={close}
          className={`fixed z-50 overflow-y-auto rounded-lg border border-gray-200 bg-white text-left shadow-xl transition-opacity duration-150 ${
            position.ready ? 'opacity-100' : 'pointer-events-none opacity-0'
          }`}
          style={{
            left: position.left,
            top: position.top,
            width: position.width,
            maxHeight: position.maxHeight || undefined,
          }}
        >
          {content}
        </div>,
        document.body,
      )}
    </span>
  )
}
