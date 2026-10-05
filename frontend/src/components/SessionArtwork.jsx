import lectureHallArt from '../assets/session-lecture-hall-art.png'
import tutorArt from '../assets/session-private-tutor-art.png'
import cafeArt from '../assets/session-friend-cafe-art.png'

const artworkByEnvironment = {
  'lecture-hall': lectureHallArt,
  'private-tutor': tutorArt,
  'friend-cafe': cafeArt,
}

/** Scenic crop collage from the approved art; interactive controls are React elements. */
export function SessionArtwork({ environmentId }) {
  return <img className="session-artwork" src={artworkByEnvironment[environmentId]} alt="" aria-hidden="true" />
}
