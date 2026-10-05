import leftRoomArt from '../assets/home-room-left.png'
import rightRoomArt from '../assets/scene-room-right.png'
import centerRoomArt from '../assets/scene-room-center-top.png'

/** Reuses the room artwork from the approved StudyMate screens. */
export function SceneBackdrop({ className = '' }) {
  return <div className={`scene-backdrop ${className}`} aria-hidden="true">
    <img className="backdrop-left" src={leftRoomArt} alt="" />
    <img className="backdrop-center" src={centerRoomArt} alt="" />
    <img className="backdrop-right" src={rightRoomArt} alt="" />
  </div>
}
