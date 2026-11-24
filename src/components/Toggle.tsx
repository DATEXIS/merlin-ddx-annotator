interface Props {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
}

export function Toggle({ label, checked, onChange }: Props) {
  return (
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <span className="text-sm text-gray-600">{label}</span>
      <button
        role="switch"
        aria-label={label}
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
          checked ? 'bg-blue-500' : 'bg-gray-300'
        }`}
      >
        <span
          className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform duration-200 ${
            checked ? 'translate-x-4' : 'translate-x-0'
          }`}
        />
      </button>
    </label>
  )
}
