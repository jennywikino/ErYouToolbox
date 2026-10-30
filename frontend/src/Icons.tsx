type Name = 'grid' | 'image' | 'search' | 'left' | 'right' | 'external' | 'folder' | 'shield'
const paths: Record<Name, string> = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  image: 'M4 4h16v16H4z M4 16l5-5 4 4 3-3 4 4 M8 8h.01',
  search: 'M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  left: 'M15 5l-7 7 7 7',
  right: 'M9 5l7 7-7 7',
  external: 'M14 3h7v7 M21 3L10 14 M10 3H3v18h18v-7',
  folder: 'M3 5h7l2 3h9v12H3z',
  shield: 'M12 2l8 4v6c0 5-8 10-8 10S4 17 4 12V6z M9 12l2 2 4-5',
}
export default function Icon({ name, className = '' }: { name: Name; className?: string }) {
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    className={className}><path d={paths[name]} /></svg>
}
