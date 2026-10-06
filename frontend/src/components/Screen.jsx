export function Screen({ background, className = '', children }) {
  return (
    <main
      className={`screen ${className}`}
      style={{ backgroundImage: `url(${background})` }}
    >
      {children}
    </main>
  )
}
